use embassy_embedded_hal::shared_bus::asynch::spi::SpiDevice;
use embassy_nrf::gpio::{AnyPin, Input, Level, Output, OutputDrive, Pull};
use embassy_nrf::peripherals::USBD;
use embassy_nrf::spim::{self, Spim};
use embassy_nrf::twim::{self, Twim};
use embassy_nrf::usb::Driver;
use embassy_nrf::{bind_interrupts, Peripherals};
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embassy_time::Delay;
use static_cell::StaticCell;

use lora_phy::iv::GenericSx126xInterfaceVariant;
use lora_phy::sx126x::{self, Sx1262, Sx126x};

bind_interrupts!(struct Irqs {
    USBD => embassy_nrf::usb::InterruptHandler<USBD>;
    SPIM3 => embassy_nrf::spim::InterruptHandler<embassy_nrf::peripherals::SPI3>;
    SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0 => embassy_nrf::twim::InterruptHandler<embassy_nrf::peripherals::TWISPI0>;
});

// ── Concrete peripheral types ────────────────────────────────────────

type SpiBus = Spim<'static, embassy_nrf::peripherals::SPI3>;
type Nss = Output<'static>;
type Iv = GenericSx126xInterfaceVariant<Output<'static>, Input<'static>>;
type RadioSpiDevice = SpiDevice<'static, NoopRawMutex, SpiBus, Nss>;
/// SX126x driver (pre-LoRa construction — LoRa::new is async).
pub type RadioDriver = Sx126x<RadioSpiDevice, Iv, Sx1262>;

/// USB driver for CDC-ACM.
pub type UsbDriver = Driver<'static, USBD, &'static embassy_nrf::usb::vbus_detect::SoftwareVbusDetect>;

/// I2C bus for an optional SSD1306 OLED.
pub type DisplayI2c = Twim<'static, embassy_nrf::peripherals::TWISPI0>;

// ── Peripheral bundles ───────────────────────────────────────────────

pub struct RadioParts {
    pub driver: RadioDriver,
    pub delay: Delay,
}

pub struct UsbParts {
    pub driver: UsbDriver,
}

pub struct DisplayParts {
    pub i2c: DisplayI2c,
}

// ── Board init ───────────────────────────────────────────────────────

pub struct Board {
    p: Peripherals,
}

impl Board {
    pub fn init() -> Self {
        let p = embassy_nrf::init(Default::default());
        Self { p }
    }

    pub fn into_parts(self) -> (RadioParts, UsbParts, Option<DisplayParts>) {
        let p = self.p;

        // ── SPI bus for SX1262 ───────────────────────────────────
        let mut spi_cfg = spim::Config::default();
        spi_cfg.frequency = spim::Frequency::M1;
        let spi = Spim::new(p.SPI3, Irqs, p.P1_11, p.P1_13, p.P1_12, spi_cfg);

        static SPI_BUS: StaticCell<embassy_sync::mutex::Mutex<NoopRawMutex, SpiBus>> =
            StaticCell::new();
        let spi_bus = SPI_BUS.init(embassy_sync::mutex::Mutex::new(spi));

        let nss = Output::new(AnyPin::from(p.P1_10), Level::High, OutputDrive::Standard);
        let spi_device = SpiDevice::new(spi_bus, nss);

        // ── SX1262 control pins ──────────────────────────────────
        let reset = Output::new(AnyPin::from(p.P1_06), Level::High, OutputDrive::Standard);
        let dio1 = Input::new(AnyPin::from(p.P1_15), Pull::Down);
        let busy = Input::new(AnyPin::from(p.P1_14), Pull::Down);

        let iv = GenericSx126xInterfaceVariant::new(reset, dio1, busy, None, None).unwrap();

        let sx_config = sx126x::Config {
            chip: Sx1262,
            tcxo_ctrl: Some(sx126x::TcxoCtrlVoltage::Ctrl1V7),
            use_dcdc: true,
            rx_boost: false,
        };

        let radio = RadioParts {
            driver: Sx126x::new(spi_device, iv, sx_config),
            delay: Delay,
        };

        // ── USB ──────────────────────────────────────────────────
        static VBUS: StaticCell<embassy_nrf::usb::vbus_detect::SoftwareVbusDetect> =
            StaticCell::new();
        let vbus = VBUS.init(embassy_nrf::usb::vbus_detect::SoftwareVbusDetect::new(true, false));
        let usb = UsbParts {
            driver: Driver::new(p.USBD, Irqs, vbus),
        };

        // ── Display (optional RAK1921 SSD1306 OLED on I2C) ──────
        // Always provide the I2C bus; display_task detects presence
        // via SSD1306 init (fails gracefully if no display attached).
        let i2c_cfg = twim::Config::default();
        let i2c = Twim::new(p.TWISPI0, Irqs, p.P0_13, p.P0_14, i2c_cfg);
        let display = Some(DisplayParts { i2c });

        (radio, usb, display)
    }
}
