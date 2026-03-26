use embassy_time::Delay;

use lora_phy::iv::GenericSx126xInterfaceVariant;
use lora_phy::sx126x::{Sx1262, Sx126x};

// ── Concrete peripheral types ────────────────────────────────────────

// TODO: replace these placeholders with real esp-hal peripheral types
//   SPI2 for SX1262 (SCK=9, MOSI=10, MISO=11, NSS=8)
//   GPIO for radio control (RST=12, DIO1=14, BUSY=13)
//   Vext pin (GPIO21) LOW to power OLED
//   I2C0 for SSD1306 (SDA=17, SCL=18)
//   USB OTG for CDC-ACM

type Iv = GenericSx126xInterfaceVariant<(), ()>;
type RadioSpiDevice = ();
pub type RadioDriver = Sx126x<RadioSpiDevice, Iv, Sx1262>;

// ── Peripheral bundles ───────────────────────────────────────────────

pub struct RadioParts {
    pub driver: RadioDriver,
    pub delay: Delay,
}

pub struct UsbParts {
    pub driver: (),
}

pub struct DisplayParts {
    pub i2c: (),
}

// ── Board init ───────────────────────────────────────────────────────

pub struct Board;

impl Board {
    pub fn init() -> Self {
        // TODO: call esp_hal::init(esp_hal::Config::default())
        Self
    }

    pub fn into_parts(self) -> (RadioParts, UsbParts, Option<DisplayParts>) {
        // TODO: wire up real peripherals once building with nightly + -Zbuild-std
        todo!("Heltec V3 peripheral init")
    }
}
