use embassy_executor::task;

use crate::board::UsbParts;
use crate::channel::{
    CommandChannel, DisplayCommand, DisplayCommandChannel, ResponseChannel,
};
use crate::protocol::{Command, ErrorCode, Response};

const MAX_FRAME: usize = 512;

#[task]
pub async fn usb_task(
    parts: UsbParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    display_commands: &'static DisplayCommandChannel,
    has_display: bool,
) {
    cfg_if::cfg_if! {
        if #[cfg(any(feature = "heltec_v3", feature = "heltec_v4"))] {
            run_serial(parts.driver, commands, responses, display_commands, has_display).await;
        } else {
            // TODO: nRF52840 uses embassy-usb CdcAcmClass — different init path
            let _ = (parts, commands, responses, display_commands, has_display);
            loop { embassy_time::Timer::after_secs(3600).await; }
        }
    }
}

#[cfg(any(feature = "heltec_v3", feature = "heltec_v4"))]
async fn run_serial(
    serial: crate::board::UsbDriver,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    display_commands: &'static DisplayCommandChannel,
    has_display: bool,
) {
    use embassy_futures::select::{select, Either};
    use embedded_io_async::{Read, Write};
    use postcard::accumulator::{CobsAccumulator, FeedResult};

    let (mut rx, mut tx) = serial.split();
    let mut cobs_buf: CobsAccumulator<MAX_FRAME> = CobsAccumulator::new();
    let mut read_buf = [0u8; 64];
    let mut write_buf = [0u8; MAX_FRAME];

    loop {
        match select(rx.read(&mut read_buf), responses.receive()).await {
            // ── Bytes from host ────────────────────────────────────
            Either::First(result) => {
                let n = match result {
                    Ok(0) | Err(_) => continue,
                    Ok(n) => n,
                };

                let mut window = &read_buf[..n];
                'cobs: while !window.is_empty() {
                    window = match cobs_buf.feed::<Command>(window) {
                        FeedResult::Consumed => break 'cobs,
                        FeedResult::OverFull(remaining) => {
                            defmt::warn!("COBS frame too large");
                            remaining
                        }
                        FeedResult::DeserError(remaining) => {
                            defmt::warn!("COBS deserialize error");
                            remaining
                        }
                        FeedResult::Success { data: cmd, remaining } => {
                            route_command(
                                cmd, commands, responses, display_commands, has_display,
                            )
                            .await;
                            remaining
                        }
                    };
                }
            }
            // ── Response to host ───────────────────────────────────
            Either::Second(response) => {
                if let Ok(buf) = postcard::to_slice_cobs(&response, &mut write_buf) {
                    let _ = tx.write_all(buf).await;
                }
            }
        }
    }
}

async fn route_command(
    cmd: Command,
    commands: &CommandChannel,
    responses: &ResponseChannel,
    display_commands: &DisplayCommandChannel,
    has_display: bool,
) {
    match cmd {
        Command::DisplayOn => {
            if has_display {
                display_commands.send(DisplayCommand::On).await;
                responses.send(Response::Ok).await;
            } else {
                responses.send(Response::Error(ErrorCode::NoDisplay)).await;
            }
        }
        Command::DisplayOff => {
            if has_display {
                display_commands.send(DisplayCommand::Off).await;
                responses.send(Response::Ok).await;
            } else {
                responses.send(Response::Error(ErrorCode::NoDisplay)).await;
            }
        }
        other => {
            commands.send(other).await;
        }
    }
}
