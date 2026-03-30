use embassy_embedded_hal::shared_bus::asynch::spi::SpiDevice;
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embassy_time::Delay;
use esp_hal::dma::{DmaRxBuf, DmaTxBuf};
use esp_hal::gpio::{Input, InputConfig, Level, Output, OutputConfig, Pull};
use esp_hal::i2c::master::{Config as I2cConfig, I2c};
use esp_hal::spi::master::{Config as SpiConfig, Spi, SpiDmaBus};
use esp_hal::spi::Mode as SpiMode;
use esp_hal::time::Rate;
use esp_hal::timer::timg::TimerGroup;
use static_cell::StaticCell;

use lora_phy::iv::GenericSx126xInterfaceVariant;
use lora_phy::sx126x::{self, Sx1262, Sx126x};

use super::traits::LoRaBoard;

// ── Concrete peripheral types ────────────────────────────────────────

type SpiBus = SpiDmaBus<'static, esp_hal::Async>;
type Nss = Output<'static>;
type Iv = GenericSx126xInterfaceVariant<Output<'static>, Input<'static>>;
type RadioSpiDevice = SpiDevice<'static, NoopRawMutex, SpiBus, Nss>;
pub type RadioDriver = Sx126x<RadioSpiDevice, Iv, Sx1262>;

pub type UsbDriver = esp_hal::otg_fs::asynch::Driver<'static>;

pub type DisplayI2c = I2c<'static, esp_hal::Async>;

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
    pub mac: [u8; 6],
}

// ── Board implementation ────────────────────────────────────────────

pub struct Board {
    p: esp_hal::peripherals::Peripherals,
}

impl LoRaBoard for Board {
    const NAME: &'static str = "Heltec V4";
    const TX_POWER_RANGE: (i8, i8) = (-9, 22);

    fn init() -> Self {
        let p = esp_hal::init(esp_hal::Config::default());
        Self { p }
    }

    fn mac_address() -> [u8; 6] {
        esp_hal::efuse::Efuse::mac_address()
    }
}

impl Board {
    pub fn into_parts(self) -> (RadioParts, UsbParts, Option<DisplayParts>) {
        let p = self.p;

        // ── esp-rtos scheduler + embassy time driver ──────────────
        let timg0 = TimerGroup::new(p.TIMG0);
        esp_rtos::start(timg0.timer0);

        // ── Vext power: GPIO36 ─────────────────────────────────────
        let vext = Output::new(p.GPIO36, Level::Low, OutputConfig::default());
        core::mem::forget(vext); // hold pin low permanently; drop would reset it

        // ── SPI + DMA for SX1262 ───────────────────────────────────
        let spi = Spi::new(
            p.SPI2,
            SpiConfig::default()
                .with_frequency(Rate::from_mhz(1))
                .with_mode(SpiMode::_0),
        )
        .expect("SPI init")
        .with_sck(p.GPIO9)
        .with_mosi(p.GPIO10)
        .with_miso(p.GPIO11)
        .with_dma(p.DMA_CH0);

        let (rx_buf, rx_desc, tx_buf, tx_desc) = esp_hal::dma_buffers!(256);
        let dma_rx = DmaRxBuf::new(rx_desc, rx_buf).expect("DMA RX buf");
        let dma_tx = DmaTxBuf::new(tx_desc, tx_buf).expect("DMA TX buf");

        let spi = spi.with_buffers(dma_rx, dma_tx).into_async();

        static SPI_BUS: StaticCell<embassy_sync::mutex::Mutex<NoopRawMutex, SpiBus>> =
            StaticCell::new();
        let spi_bus = SPI_BUS.init(embassy_sync::mutex::Mutex::new(spi));

        let nss = Output::new(p.GPIO8, Level::High, OutputConfig::default());
        let spi_device = SpiDevice::new(spi_bus, nss);

        // ── SX1262 control pins ────────────────────────────────────
        let reset = Output::new(p.GPIO12, Level::High, OutputConfig::default());
        let dio1 = Input::new(p.GPIO14, InputConfig::default().with_pull(Pull::Down));
        let busy = Input::new(p.GPIO13, InputConfig::default().with_pull(Pull::Down));

        let iv = GenericSx126xInterfaceVariant::new(reset, dio1, busy, None, None)
            .expect("SX1262 interface init");

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

        // ── USB OTG CDC-ACM ────────────────────────────────────────
        // Note: switches internal USB PHY from Serial-JTAG to OTG.
        // espflash --monitor will stop working after this point.
        let usb_inst = esp_hal::otg_fs::Usb::new(p.USB0, p.GPIO20, p.GPIO19);
        static EP_OUT_BUF: StaticCell<[u8; 1024]> = StaticCell::new();
        let ep_out_buf = EP_OUT_BUF.init([0u8; 1024]);
        let usb = UsbParts {
            driver: esp_hal::otg_fs::asynch::Driver::new(
                usb_inst,
                ep_out_buf,
                esp_hal::otg_fs::asynch::Config::default(),
            ),
        };

        // ── Display (SSD1315 OLED on I2C, 0x3C) ───────────────────
        let mut display_rst = Output::new(p.GPIO21, Level::Low, OutputConfig::default());
        esp_hal::delay::Delay::new().delay_millis(10);
        display_rst.set_high();
        esp_hal::delay::Delay::new().delay_millis(10);
        core::mem::forget(display_rst); // hold reset high permanently

        let i2c = I2c::new(p.I2C0, I2cConfig::default())
            .expect("I2C init")
            .with_sda(p.GPIO17)
            .with_scl(p.GPIO18)
            .into_async();
        let mac = Self::mac_address();
        let display = Some(DisplayParts { i2c, mac });

        (radio, usb, display)
    }
}
