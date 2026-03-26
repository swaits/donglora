#![no_std]
#![no_main]

mod board;
mod channel;
mod display;
mod protocol;
mod radio;
mod usb;

use embassy_executor::Spawner;

use crate::channel::{CommandChannel, ResponseChannel, StatusWatch};

cfg_if::cfg_if! {
    if #[cfg(feature = "rak_4631")] {
        use panic_probe as _;
    }
}

static COMMANDS: CommandChannel = CommandChannel::new();
static RESPONSES: ResponseChannel = ResponseChannel::new();
static STATUS: StatusWatch = StatusWatch::new();

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let board = board::Board::init();
    let (radio, usb, display) = board.into_parts();

    spawner.spawn(radio::radio_task(radio, &COMMANDS, &RESPONSES, &STATUS)).unwrap();
    spawner.spawn(usb::usb_task(usb, &COMMANDS, &RESPONSES)).unwrap();

    if let Some(dp) = display {
        spawner.spawn(display::display_task(dp, &STATUS)).unwrap();
    }
}
