use defmt::{error, info, warn};
use embassy_executor::task;
use embassy_futures::select::{select, Either};
use embassy_time::Delay;
use lora_phy::mod_params::{PacketStatus, RadioError};
use lora_phy::{LoRa, RxMode};

use crate::board::{RadioDriver, RadioParts};
use crate::channel::{CommandChannel, RadioState, RadioStatus, ResponseChannel, StatusWatch};
use crate::protocol::{self, Command, ErrorCode, RadioConfig, Response};

const MAX_PAYLOAD: usize = protocol::MAX_PAYLOAD;

type Radio = LoRa<RadioDriver, Delay>;

#[task]
pub async fn radio_task(
    parts: RadioParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    status: &'static StatusWatch,
) {
    let mut state = RadioStatus::default();
    status.sender().send(state.clone());

    let mut lora = match LoRa::new(parts.driver, false, parts.delay).await {
        Ok(l) => l,
        Err(e) => {
            error!("radio init failed: {}", e);
            responses.send(Response::Error(ErrorCode::InvalidConfig)).await;
            loop {
                let cmd = commands.receive().await;
                if let Command::Ping = cmd {
                    responses.send(Response::Pong).await;
                } else {
                    responses.send(Response::Error(ErrorCode::InvalidConfig)).await;
                }
            }
        }
    };

    info!("radio initialized");
    let mut rx_buf = [0u8; MAX_PAYLOAD];

    loop {
        if state.state == RadioState::Receiving {
            match select(rx_once(&mut lora, &state, &mut rx_buf), commands.receive()).await {
                Either::First(rx_result) => {
                    match rx_result {
                        Ok((len, pkt_status)) => {
                            state.rx_count = state.rx_count.wrapping_add(1);
                            let rssi = pkt_status.rssi;
                            let snr = pkt_status.snr;
                            state.last_rssi = Some(rssi);
                            state.last_snr = Some(snr);
                            status.sender().send(state.clone());

                            let mut payload = heapless::Vec::new();
                            let _ = payload.extend_from_slice(&rx_buf[..len as usize]);
                            responses
                                .send(Response::RxPacket {
                                    rssi,
                                    snr,
                                    payload,
                                })
                                .await;

                            if let Err(e) = start_rx(&mut lora, &state).await {
                                warn!("restart RX failed: {}", e);
                                state.state = RadioState::Idle;
                                status.sender().send(state.clone());
                            }
                        }
                        Err(e) => {
                            warn!("RX error: {}", e);
                            if start_rx(&mut lora, &state).await.is_err() {
                                state.state = RadioState::Idle;
                                status.sender().send(state.clone());
                            }
                        }
                    }
                }
                Either::Second(cmd) => {
                    handle_cmd(cmd, &mut lora, &mut state, responses, status, &mut rx_buf).await;
                }
            }
        } else {
            let cmd = commands.receive().await;
            handle_cmd(cmd, &mut lora, &mut state, responses, status, &mut rx_buf).await;
        }
    }
}

async fn handle_cmd(
    cmd: Command,
    lora: &mut Radio,
    state: &mut RadioStatus,
    responses: &ResponseChannel,
    status: &StatusWatch,
    _rx_buf: &mut [u8],
) {
    match cmd {
        Command::Ping => {
            responses.send(Response::Pong).await;
        }
        Command::GetConfig => {
            if let Some(cfg) = state.config {
                responses.send(Response::Config(cfg)).await;
            } else {
                responses.send(Response::Error(ErrorCode::NotConfigured)).await;
            }
        }
        Command::SetConfig(cfg) => {
            state.config = Some(cfg);
            status.sender().send(state.clone());
            responses.send(Response::Ok).await;
        }
        Command::StartRx => {
            if state.config.is_some() {
                match start_rx(lora, state).await {
                    Ok(()) => {
                        state.state = RadioState::Receiving;
                        status.sender().send(state.clone());
                        responses.send(Response::Ok).await;
                    }
                    Err(e) => {
                        warn!("StartRx failed: {}", e);
                        responses.send(Response::Error(ErrorCode::InvalidConfig)).await;
                    }
                }
            } else {
                responses.send(Response::Error(ErrorCode::NotConfigured)).await;
            }
        }
        Command::StopRx => {
            let _ = lora.enter_standby().await;
            state.state = RadioState::Idle;
            status.sender().send(state.clone());
            responses.send(Response::Ok).await;
        }
        Command::DisplayOn | Command::DisplayOff => {}
        Command::Transmit { config, payload } => {
            let tx_config = config.or(state.config);
            if let Some(cfg) = tx_config {
                let was_receiving = state.state == RadioState::Receiving;
                state.state = RadioState::Transmitting;
                status.sender().send(state.clone());

                match do_tx(lora, &cfg, &payload).await {
                    Ok(()) => {
                        state.tx_count = state.tx_count.wrapping_add(1);
                        responses.send(Response::TxDone).await;
                    }
                    Err(e) => {
                        warn!("TX failed: {}", e);
                        responses.send(Response::Error(ErrorCode::TxTimeout)).await;
                    }
                }

                state.state = if was_receiving {
                    if start_rx(lora, state).await.is_ok() {
                        RadioState::Receiving
                    } else {
                        RadioState::Idle
                    }
                } else {
                    RadioState::Idle
                };
                status.sender().send(state.clone());
            } else {
                responses.send(Response::Error(ErrorCode::NotConfigured)).await;
            }
        }
    }
}

// ── LoRa helpers ─────────────────────────────────────────────────────

fn to_bw(bw: protocol::Bandwidth) -> lora_phy::mod_params::Bandwidth {
    use lora_phy::mod_params::Bandwidth::*;
    match bw {
        protocol::Bandwidth::Khz7 => _7KHz,
        protocol::Bandwidth::Khz10 => _10KHz,
        protocol::Bandwidth::Khz15 => _15KHz,
        protocol::Bandwidth::Khz20 => _20KHz,
        protocol::Bandwidth::Khz31 => _31KHz,
        protocol::Bandwidth::Khz41 => _41KHz,
        protocol::Bandwidth::Khz62 => _62KHz,
        protocol::Bandwidth::Khz125 => _125KHz,
        protocol::Bandwidth::Khz250 => _250KHz,
        protocol::Bandwidth::Khz500 => _500KHz,
    }
}

fn to_sf(sf: u8) -> lora_phy::mod_params::SpreadingFactor {
    use lora_phy::mod_params::SpreadingFactor::*;
    match sf {
        5 => _5,
        6 => _6,
        8 => _8,
        9 => _9,
        10 => _10,
        11 => _11,
        12 => _12,
        _ => _7,
    }
}

fn to_cr(cr: u8) -> lora_phy::mod_params::CodingRate {
    use lora_phy::mod_params::CodingRate::*;
    match cr {
        5 => _4_5,
        6 => _4_6,
        7 => _4_7,
        8 => _4_8,
        _ => {
            debug_assert!(false, "BUG: unvalidated CR {}", cr);
            _4_5
        }
    }
}

async fn start_rx(lora: &mut Radio, state: &RadioStatus) -> Result<(), RadioError> {
    let cfg = state.config.unwrap();
    let mdltn = lora.create_modulation_params(to_sf(cfg.sf), to_bw(cfg.bw), to_cr(cfg.cr), cfg.freq_hz)?;
    let pkt = lora.create_rx_packet_params(8, false, MAX_PAYLOAD as u8, true, false, &mdltn)?;
    lora.prepare_for_rx(RxMode::Continuous, &mdltn, &pkt).await?;
    Ok(())
}

async fn rx_once(
    lora: &mut Radio,
    state: &RadioStatus,
    buf: &mut [u8],
) -> Result<(u8, PacketStatus), RadioError> {
    let cfg = state.config.unwrap();
    let mdltn = lora.create_modulation_params(to_sf(cfg.sf), to_bw(cfg.bw), to_cr(cfg.cr), cfg.freq_hz)?;
    let pkt = lora.create_rx_packet_params(8, false, MAX_PAYLOAD as u8, true, false, &mdltn)?;
    lora.rx(&pkt, buf).await
}

async fn do_tx(lora: &mut Radio, cfg: &RadioConfig, payload: &[u8]) -> Result<(), RadioError> {
    let mdltn = lora.create_modulation_params(to_sf(cfg.sf), to_bw(cfg.bw), to_cr(cfg.cr), cfg.freq_hz)?;
    let mut tx_pkt = lora.create_tx_packet_params(8, false, true, false, &mdltn)?;
    lora.prepare_for_tx(&mdltn, &mut tx_pkt, cfg.tx_power_dbm as i32, payload).await?;
    lora.tx().await?;
    Ok(())
}
