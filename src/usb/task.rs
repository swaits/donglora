//! USB CDC-ACM task: COBS-framed fixed-size LE command/response protocol.
//!
//! Reads COBS frames from USB, decodes them, parses commands, routes them
//! to the radio or display task, and sends COBS-framed responses back.

use defmt::warn;
use embassy_executor::task;
use embassy_futures::join::join;
use embassy_usb::class::cdc_acm::{CdcAcmClass, Receiver, Sender, State};
use embassy_usb::Builder;
use static_cell::StaticCell;

use crate::board::UsbParts;
use crate::channel::{
    CommandChannel, DisplayCommand, DisplayCommandChannel, ResponseChannel,
};
use crate::protocol::{Command, ErrorCode, Response};

const MAX_FRAME: usize = 512;
const MAX_PACKET: usize = 64;

// Worst case: tag(1) + rssi(2) + snr(2) + len(2) + payload(256) = 263 bytes.
// COBS adds ceil(263/254)+1 = 3 bytes. 266 < 512. Plenty of room.
const _: () = assert!(
    MAX_FRAME >= crate::protocol::MAX_PAYLOAD + 64,
    "MAX_FRAME too small for max payload + COBS overhead"
);

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
    let mut cobs_encode_buf = [0u8; MAX_FRAME];

    // COBS accumulator: collect bytes until 0x00 sentinel
    let mut frame_buf = [0u8; MAX_FRAME];
    let mut frame_len: usize = 0;

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
                        frame_len = 0; // reset accumulator
                        embassy_time::Timer::after_millis(100).await;
                        continue;
                    }
                };

                // Feed bytes into the COBS accumulator
                for &byte in &read_buf[..n] {
                    if byte == 0x00 {
                        // End of COBS frame — decode and parse
                        if frame_len > 0 {
                            let mut decode_buf = [0u8; MAX_FRAME];
                            if let Some(decoded_len) =
                                donglora_cobs::decode(&frame_buf[..frame_len], &mut decode_buf)
                            {
                                if let Some(cmd) = Command::from_bytes(&decode_buf[..decoded_len]) {
                                    route_command(
                                        cmd, commands, responses, display_commands, has_display,
                                    )
                                    .await;
                                }
                            }
                        }
                        frame_len = 0;
                    } else if frame_len < MAX_FRAME {
                        frame_buf[frame_len] = byte;
                        frame_len += 1;
                    } else {
                        // Frame too large — discard
                        frame_len = 0;
                    }
                }
            }
            Either3::Second(response) => {
                // Serialize response to fixed-size LE bytes, then COBS encode
                let raw_len = response.write_to(&mut write_buf);
                let encoded_len = donglora_cobs::encode(&write_buf[..raw_len], &mut cobs_encode_buf)
                    .unwrap_or(0);
                // Append 0x00 sentinel
                if encoded_len < cobs_encode_buf.len() {
                    cobs_encode_buf[encoded_len] = 0x00;
                    let frame = &cobs_encode_buf[..encoded_len + 1];
                    for chunk in frame.chunks(MAX_PACKET) {
                        if sender.write_packet(chunk).await.is_err() {
                            warn!("USB write failed, response dropped");
                            break;
                        }
                    }
                } else {
                    warn!("COBS encode buffer overflow");
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


// ── COBS compliance tests (IEEE/ACM Cheshire & Baker 1999) ──────

#[cfg(test)]
mod tests {
    use super::cobs_decode;

    fn decode(encoded: &[u8]) -> Option<Vec<u8>> {
        let mut buf = vec![0u8; 512];
        cobs_decode(encoded, &mut buf).map(|n| buf[..n].to_vec())
    }

    // Wikipedia canonical vectors
    #[test]
    fn empty_input() {
        assert_eq!(decode(&[0x01]), Some(vec![]));
    }

    #[test]
    fn single_zero() {
        assert_eq!(decode(&[0x01, 0x01]), Some(vec![0x00]));
    }

    #[test]
    fn two_zeros() {
        assert_eq!(decode(&[0x01, 0x01, 0x01]), Some(vec![0x00, 0x00]));
    }

    #[test]
    fn single_nonzero() {
        assert_eq!(decode(&[0x02, 0x11]), Some(vec![0x11]));
    }

    #[test]
    fn zero_delimited() {
        assert_eq!(
            decode(&[0x01, 0x02, 0x11, 0x01]),
            Some(vec![0x00, 0x11, 0x00])
        );
    }

    #[test]
    fn mixed_with_zero() {
        assert_eq!(
            decode(&[0x03, 0x11, 0x22, 0x02, 0x33]),
            Some(vec![0x11, 0x22, 0x00, 0x33])
        );
    }

    #[test]
    fn no_zeros() {
        assert_eq!(
            decode(&[0x05, 0x11, 0x22, 0x33, 0x44]),
            Some(vec![0x11, 0x22, 0x33, 0x44])
        );
    }

    #[test]
    fn nonzero_then_trailing_zeros() {
        assert_eq!(
            decode(&[0x02, 0x11, 0x01, 0x01, 0x01]),
            Some(vec![0x11, 0x00, 0x00, 0x00])
        );
    }

    #[test]
    fn all_zeros_4() {
        assert_eq!(
            decode(&[0x01, 0x01, 0x01, 0x01, 0x01]),
            Some(vec![0x00, 0x00, 0x00, 0x00])
        );
    }

    #[test]
    fn all_ff_4() {
        assert_eq!(
            decode(&[0x05, 0xFF, 0xFF, 0xFF, 0xFF]),
            Some(vec![0xFF, 0xFF, 0xFF, 0xFF])
        );
    }

    #[test]
    fn alternating_zero_nonzero() {
        assert_eq!(
            decode(&[0x01, 0x02, 0x01, 0x02, 0x02, 0x02, 0x03]),
            Some(vec![0x00, 0x01, 0x00, 0x02, 0x00, 0x03])
        );
    }

    // The Ping case that caught the original bug
    #[test]
    fn ping_command_tag_zero() {
        assert_eq!(decode(&[0x01, 0x01]), Some(vec![0x00]));
    }

    // 254-byte block boundary (code 0xFF = 254 data bytes, no implicit zero)
    #[test]
    fn block_254_nonzero() {
        let input: Vec<u8> = (1..=254).collect();
        let mut encoded = vec![0xFF];
        encoded.extend(1u8..=254);
        assert_eq!(decode(&encoded), Some(input));
    }

    // 255 non-zero bytes: first 254 as one block, then 1 leftover
    #[test]
    fn block_255_nonzero() {
        let input: Vec<u8> = (1..=255).map(|i| i as u8).collect();
        let mut encoded = vec![0xFF];
        encoded.extend(1u8..=254);
        encoded.push(0x02); // code for 1 data byte
        encoded.push(0xFF); // the 255th byte
        assert_eq!(decode(&encoded), Some(input));
    }

    // Error cases
    #[test]
    fn unexpected_zero_in_data() {
        assert_eq!(decode(&[0x00]), None);
    }

    #[test]
    fn truncated_input() {
        // Code says 3 data bytes follow, but only 1 available
        assert_eq!(decode(&[0x04, 0x11]), None);
    }

    #[test]
    fn empty_encoded() {
        assert_eq!(decode(&[]), Some(vec![]));
    }
}
