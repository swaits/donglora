use embassy_executor::task;

use crate::board::UsbParts;
use crate::channel::{CommandChannel, DisplayCommandChannel, ResponseChannel};

#[task]
pub async fn usb_task(
    parts: UsbParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    display_commands: &'static DisplayCommandChannel,
    has_display: bool,
) {
    let _driver = parts.driver;
    let _ = commands;
    let _ = responses;
    let _ = display_commands;
    let _ = has_display;

    // TODO: build embassy_usb CDC-ACM class from driver
    // TODO: COBS-framed postcard ser/de loop:
    //   select! {
    //       bytes = cdc_read() => {
    //           let cmd: Command = deserialize(bytes);
    //           match cmd {
    //               Command::DisplayOn => route_display(DisplayCommand::On),
    //               Command::DisplayOff => route_display(DisplayCommand::Off),
    //               other => commands.send(other).await,
    //           }
    //       }
    //       resp = responses.receive() => serialize Response → cdc_write()
    //   }
    //
    // Display command routing:
    //   async fn route_display(cmd, display_commands, has_display, responses) {
    //       if has_display {
    //           display_commands.send(cmd).await;
    //           responses.send(Response::Ok).await;
    //       } else {
    //           responses.send(Response::Error(ErrorCode::NoDisplay)).await;
    //       }
    //   }

    loop {
        embassy_time::Timer::after_secs(1).await;
    }
}
