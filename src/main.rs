#![no_std]
#![no_main]

mod board;
mod channel;
mod display;
mod protocol;
mod radio;
mod usb;

use embassy_executor::Spawner;

use crate::channel::{CommandChannel, DisplayCommandChannel, ResponseChannel, StatusWatch};

cfg_if::cfg_if! {
    if #[cfg(feature = "rak_wisblock_4631")] {
        use panic_probe as _;
    } else if #[cfg(any(feature = "heltec_v3", feature = "heltec_v4"))] {
        use esp_backtrace as _;
        use esp_println as _;
    }
}

static COMMANDS: CommandChannel = CommandChannel::new();
static RESPONSES: ResponseChannel = ResponseChannel::new();
static STATUS: StatusWatch = StatusWatch::new();
static DISPLAY_COMMANDS: DisplayCommandChannel = DisplayCommandChannel::new();

cfg_if::cfg_if! {
    if #[cfg(feature = "rak_wisblock_4631")] {
        #[embassy_executor::main]
        async fn main(spawner: Spawner) {
            run(spawner).await;
        }
    } else if #[cfg(any(feature = "heltec_v3", feature = "heltec_v4"))] {
        #[esp_hal_embassy::main]
        async fn main(spawner: Spawner) {
            run(spawner).await;
        }
    }
}

async fn run(spawner: Spawner) {
    let board = board::Board::init();
    let (radio, usb, display) = board.into_parts();

    let has_display = display.is_some();

    spawner.spawn(radio::radio_task(radio, &COMMANDS, &RESPONSES, &STATUS)).unwrap();
    spawner.spawn(usb::usb_task(usb, &COMMANDS, &RESPONSES, &DISPLAY_COMMANDS, has_display)).unwrap();

    if let Some(dp) = display {
        spawner.spawn(display::display_task(dp, &STATUS, &DISPLAY_COMMANDS)).unwrap();
    }
}
