use embassy_executor::task;
use embassy_futures::join::join;
use embassy_usb::class::cdc_acm::{CdcAcmClass, Receiver, Sender, State};
use embassy_usb::Builder;
use postcard::accumulator::{CobsAccumulator, FeedResult};
use static_cell::StaticCell;

use crate::board::UsbParts;
use crate::channel::{
    CommandChannel, DisplayCommand, DisplayCommandChannel, ResponseChannel,
};
use crate::protocol::{Command, ErrorCode, Response};

const MAX_FRAME: usize = 512;
const MAX_PACKET: usize = 64;

#[task]
pub async fn usb_task(
    parts: UsbParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    display_commands: &'static DisplayCommandChannel,
    has_display: bool,
) {
    // ── Build embassy-usb device with CDC-ACM class ────────────────
    let mut config = embassy_usb::Config::new(0x1209, 0x5741);
    config.manufacturer = Some("DongLoRa");
    config.product = Some("DongLoRa LoRa Radio");
    config.serial_number = Some("001");
    config.device_class = 0xEF;
    config.device_sub_class = 0x02;
    config.device_protocol = 0x01;
    config.composite_with_iads = true;

    static DESC_BUF: StaticCell<[u8; 256]> = StaticCell::new();
    static CONF_BUF: StaticCell<[u8; 256]> = StaticCell::new();
    static BOS_BUF: StaticCell<[u8; 256]> = StaticCell::new();
    static CTRL_BUF: StaticCell<[u8; 64]> = StaticCell::new();
    static CDC_STATE: StaticCell<State> = StaticCell::new();

    let desc_buf = DESC_BUF.init([0; 256]);
    let conf_buf = CONF_BUF.init([0; 256]);
    let bos_buf = BOS_BUF.init([0; 256]);
    let ctrl_buf = CTRL_BUF.init([0; 64]);
    let cdc_state = CDC_STATE.init(State::new());

    let mut builder = Builder::new(
        parts.driver,
        config,
        desc_buf,
        conf_buf,
        bos_buf,
        ctrl_buf,
    );

    let class = CdcAcmClass::new(&mut builder, cdc_state, MAX_PACKET as u16);
    let mut usb_dev = builder.build();
    let (sender, receiver) = class.split();

    // ── Run USB device + protocol loop concurrently ────────────────
    join(
        usb_dev.run(),
        protocol_loop(sender, receiver, commands, responses, display_commands, has_display),
    )
    .await;
}

async fn protocol_loop<'d, D: embassy_usb_driver::Driver<'d>>(
    mut sender: Sender<'d, D>,
    mut receiver: Receiver<'d, D>,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    display_commands: &'static DisplayCommandChannel,
    has_display: bool,
) {
    use embassy_futures::select::select3;
    use embassy_futures::select::Either3;

    let mut read_buf = [0u8; MAX_PACKET];
    let mut write_buf = [0u8; MAX_FRAME];
    let mut cobs_buf: CobsAccumulator<MAX_FRAME> = CobsAccumulator::new();
    let mut was_connected = false;

    loop {
        match select3(
            receiver.read_packet(&mut read_buf),
            responses.receive(),
            embassy_time::Timer::after_millis(250),
        )
        .await
        {
            Either3::First(result) => {
                let n = match result {
                    Ok(0) => continue,
                    Ok(n) => n,
                    Err(_) => {
                        cobs_buf = CobsAccumulator::new();
                        embassy_time::Timer::after_millis(100).await;
                        continue;
                    }
                };

                let mut window = &read_buf[..n];
                'cobs: while !window.is_empty() {
                    window = match cobs_buf.feed::<Command>(window) {
                        FeedResult::Consumed => break 'cobs,
                        FeedResult::OverFull(remaining) => remaining,
                        FeedResult::DeserError(remaining) => remaining,
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
            Either3::Second(response) => {
                if let Ok(buf) = postcard::to_slice_cobs(&response, &mut write_buf) {
                    for chunk in buf.chunks(MAX_PACKET) {
                        let _ = sender.write_packet(chunk).await;
                    }
                }
            }
            Either3::Third(()) => {
                // Poll DTR every 250ms to detect host disconnect
            }
        }

        // Check DTR after every select wake
        let connected = receiver.dtr();
        if was_connected && !connected && has_display {
            display_commands.send(DisplayCommand::Reset).await;
        }
        if !was_connected && connected && has_display {
            display_commands.send(DisplayCommand::On).await;
        }
        was_connected = connected;
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
