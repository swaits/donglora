use esp_hal::gpio::{GpioPin, Input, Output, PullDown, PushPull};
use esp_hal::peripherals::SPI2;
use esp_hal::spi::master::Spi;
use esp_hal::spi::SpiMode;
use esp_hal::i2c::I2c;
use esp_hal::peripherals::I2C0;
use esp_hal::Delay;

use lora_phy::iv::GenericSx126xInterfaceVariant;
use lora_phy::sx126x::{self, Sx1262, Sx126x};
use lora_phy::LoRa;

/// Board name shown on the display dashboard.
pub const BOARD_NAME: &str = "Heltec V3";

// ── Concrete peripheral types ────────────────────────────────────────

type Iv = GenericSx126xInterfaceVariant<Output<'static, GpioPin<8>>, Input<'static, GpioPin<14>>>;
type RadioSpi = Spi<'static, SPI2>;
type RadioDriver = Sx126x<RadioSpi, Iv, Sx1262>;

/// Fully-constructed LoRa radio driver.
pub type Radio = LoRa<RadioDriver, Delay>;

/// USB driver for CDC-ACM.
// TODO: define concrete USB OTG type once esp-hal USB support is wired up
pub type UsbDriver = ();

/// I2C bus for the built-in SSD1306 OLED.
pub type DisplayI2c = I2c<'static, I2C0>;

// ── Peripheral bundles ───────────────────────────────────────────────

pub struct RadioParts {
    pub radio: Radio,
}

pub struct UsbParts {
    pub driver: UsbDriver,
}

pub struct DisplayParts {
    pub i2c: DisplayI2c,
}

// ── Board init ───────────────────────────────────────────────────────

pub struct Board {
    p: esp_hal::peripherals::Peripherals,
}

impl Board {
    pub fn init() -> Self {
        let p = esp_hal::init(esp_hal::Config::default());
        Self { p }
    }

    pub fn into_parts(self) -> (RadioParts, UsbParts, Option<DisplayParts>) {
        let _p = self.p;

        // TODO: implement Heltec V3 peripheral init
        // - SPI2 for SX1262 (SCK=9, MOSI=10, MISO=11, NSS=8)
        // - GPIO for radio control (RST=12, DIO1=14, BUSY=13)
        // - Vext pin (GPIO21) LOW to power OLED
        // - I2C0 for SSD1306 (SDA=17, SCL=18)
        // - USB OTG for CDC-ACM

        todo!("Heltec V3 peripheral init — requires espup toolchain to develop")
    }
}
