use defmt::error;
use embassy_executor::task;
use lora_phy::LoRa;

use crate::board::RadioParts;
use crate::channel::{CommandChannel, RadioState, RadioStatus, ResponseChannel, StatusWatch};
use crate::protocol::{Command, ErrorCode, Response};

#[task]
pub async fn radio_task(
    parts: RadioParts,
    commands: &'static CommandChannel,
    responses: &'static ResponseChannel,
    status: &'static StatusWatch,
) {
    let mut state = RadioStatus::default();
    status.sender().send(state.clone());

    let lora = LoRa::new(parts.driver, false, parts.delay).await;
    let mut lora = match lora {
        Ok(l) => l,
        Err(e) => {
            error!("radio init failed: {}", e);
            responses.send(Response::Error(ErrorCode::InvalidConfig)).await;
            // Cannot proceed without radio — idle forever.
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

    loop {
        let cmd = commands.receive().await;
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
                // TODO: apply config to lora hardware
                status.sender().send(state.clone());
            }
            Command::StartRx => {
                if state.config.is_some() {
                    state.state = RadioState::Receiving;
                    // TODO: start continuous RX via lora
                    status.sender().send(state.clone());
                } else {
                    responses.send(Response::Error(ErrorCode::NotConfigured)).await;
                }
            }
            Command::StopRx => {
                state.state = RadioState::Idle;
                // TODO: put lora radio into standby
                status.sender().send(state.clone());
            }
            Command::DisplayOn | Command::DisplayOff => {
                // Routed by usb_task to display — should never reach radio.
            }
            Command::Transmit { config, payload } => {
                let tx_config = config.or(state.config);
                if let Some(_cfg) = tx_config {
                    let was_receiving = state.state == RadioState::Receiving;
                    state.state = RadioState::Transmitting;
                    status.sender().send(state.clone());

                    // TODO: transmit payload via lora
                    let _ = &mut lora;
                    let _ = payload;

                    state.tx_count = state.tx_count.wrapping_add(1);
                    responses.send(Response::TxDone).await;

                    state.state = if was_receiving {
                        RadioState::Receiving
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
}
