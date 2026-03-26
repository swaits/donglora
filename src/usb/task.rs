use embassy_executor::task;

use crate::board::UsbParts;
use crate::channel::{CommandChannel, ResponseChannel};

#[task]
pub async fn usb_task(
    parts: UsbParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
) {
    let _driver = parts.driver;
    let _ = commands;
    let _ = responses;

    // TODO: build embassy_usb CDC-ACM class from driver
    // TODO: COBS-framed postcard ser/de loop:
    //   select! {
    //       bytes = cdc_read() => deserialize Command → commands.send()
    //       resp  = responses.receive() => serialize Response → cdc_write()
    //   }

    loop {
        embassy_time::Timer::after_secs(1).await;
    }
}
