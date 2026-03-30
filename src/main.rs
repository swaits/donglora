//! DongLoRa firmware — transparent LoRa radio over USB.
//!
//! Three async tasks communicate via static channels:
//!
//! ```text
//! usb_task ──Command──► radio_task ──► SX1262
//!          ◄──Response──     │
//!                       StatusWatch
//!                            ▼
//!                      display_task (optional)
//! ```
//!
//! The host drives everything. The radio idles until commanded.

#![no_std]
#![no_main]

mod board;
mod channel;
mod display;
mod protocol;
mod radio;
mod usb;

use embassy_executor::Spawner;

use crate::board::LoRaBoard;
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
        #[esp_rtos::main]
        async fn main(spawner: Spawner) {
            run(spawner).await;
        }
    }
}

async fn run(spawner: Spawner) {
    let board = <board::Board as LoRaBoard>::init();
    let (radio, usb, display) = board.into_parts();

    let has_display = display.is_some();

    spawner
        .spawn(radio::radio_task(radio, &COMMANDS, &RESPONSES, &STATUS))
        .expect("spawn radio_task");
    spawner
        .spawn(usb::usb_task(usb, &COMMANDS, &RESPONSES, &DISPLAY_COMMANDS, has_display))
        .expect("spawn usb_task");

    if let Some(dp) = display {
        spawner
            .spawn(display::display_task(dp, &STATUS, &DISPLAY_COMMANDS))
            .expect("spawn display_task");
    }
}
