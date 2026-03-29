use core::fmt::Write;

use embedded_graphics::mono_font::ascii::{FONT_6X10, FONT_9X15_BOLD};
use embedded_graphics::mono_font::MonoTextStyle;
use embedded_graphics::pixelcolor::BinaryColor;
use embedded_graphics::prelude::*;
use embedded_graphics::primitives::{Line, PrimitiveStyle, Rectangle};
use embedded_graphics::text::renderer::CharacterStyle;
use embedded_graphics::text::{Alignment, Text};
use heapless::String;

use crate::channel::{RadioState, RadioStatus};
use crate::protocol::Bandwidth;

/// RSSI ring buffer length — one bar per 2px across 128px.
pub const RSSI_HISTORY_LEN: usize = 64;

// Layout constants
const W: i32 = 128;
const FONT_H: i32 = 10;
const SEP_Y: i32 = 43;
const SPARK_TOP: i32 = 45;
const SPARK_H: i32 = 19; // y=45..63

// RSSI mapping range (dBm)
const RSSI_MIN: i16 = -120;
const RSSI_MAX: i16 = 0;

/// Render the main status dashboard.
pub fn dashboard(
    target: &mut impl DrawTarget<Color = BinaryColor>,
    status: &RadioStatus,
    rssi_history: &[i16; RSSI_HISTORY_LEN],
    tx_history: &[bool; RSSI_HISTORY_LEN],
    rssi_count: usize,
    board_name: &str,
    version: &str,
) {
    let _ = target.clear(BinaryColor::Off);
    let style = MonoTextStyle::new(&FONT_6X10, BinaryColor::On);

    match status.config {
        Some(cfg) => {
            // Row 0: state + frequency, TX power right-justified
            let mut buf: String<32> = String::new();
            let freq_mhz = cfg.freq_hz / 1_000_000;
            let freq_khz = (cfg.freq_hz % 1_000_000) / 1_000;
            let _ = write!(buf, "     {}.{:03}MHz", freq_mhz, freq_khz);
            Text::new(&buf, Point::new(0, FONT_H - 1), style)
                .draw(target)
                .ok();
            buf.clear();
            let _ = write!(buf, "{}dBm", cfg.tx_power_dbm);
            Text::with_alignment(&buf, Point::new(W - 1, FONT_H - 1), style, Alignment::Right)
                .draw(target)
                .ok();

            // State indicator: inverted "RX" or "TX", plain "IDLE"
            match status.state {
                RadioState::Idle => {
                    Text::new("IDLE", Point::new(0, FONT_H - 1), style)
                        .draw(target)
                        .ok();
                }
                RadioState::Receiving => {
                    let x = 0;
                    let char_w = 6;
                    let text_w = 2 * char_w; // "RX" = 2 chars
                    let mut inv_style = MonoTextStyle::new(&FONT_6X10, BinaryColor::Off);
                    inv_style.set_background_color(Some(BinaryColor::On));
                    Rectangle::new(Point::new(x, 0), Size::new(text_w as u32, FONT_H as u32))
                        .into_styled(PrimitiveStyle::with_fill(BinaryColor::On))
                        .draw(target)
                        .ok();
                    Text::new("RX", Point::new(x, FONT_H - 1), inv_style)
                        .draw(target)
                        .ok();
                }
                RadioState::Transmitting => {
                    let char_w = 6;
                    let x = 2 * char_w; // start at column 2 (third character position)
                    let text_w = 2 * char_w; // "TX" = 2 chars
                    let mut inv_style = MonoTextStyle::new(&FONT_6X10, BinaryColor::Off);
                    inv_style.set_background_color(Some(BinaryColor::On));
                    Rectangle::new(Point::new(x, 0), Size::new(text_w as u32, FONT_H as u32))
                        .into_styled(PrimitiveStyle::with_fill(BinaryColor::On))
                        .draw(target)
                        .ok();
                    Text::new("TX", Point::new(x, FONT_H - 1), inv_style)
                        .draw(target)
                        .ok();
                }
            }

            // Row 1: BW (full) SF CR
            buf.clear();
            let bw_str = match cfg.bw {
                Bandwidth::Khz7 => "7.8kHz",
                Bandwidth::Khz10 => "10.4kHz",
                Bandwidth::Khz15 => "15.6kHz",
                Bandwidth::Khz20 => "20.8kHz",
                Bandwidth::Khz31 => "31.2kHz",
                Bandwidth::Khz41 => "41.7kHz",
                Bandwidth::Khz62 => "62.5kHz",
                Bandwidth::Khz125 => "125kHz",
                Bandwidth::Khz250 => "250kHz",
                Bandwidth::Khz500 => "500kHz",
            };
            let _ = write!(buf, "{} SF{} CR4/{}", bw_str, cfg.sf, cfg.cr);
            Text::new(&buf, Point::new(0, FONT_H * 2 - 1), style)
                .draw(target)
                .ok();

            // Row 2: packet counters
            buf.clear();
            let _ = write!(buf, "RX:{} TX:{}", status.rx_count, status.tx_count);
            Text::new(&buf, Point::new(0, FONT_H * 3 - 1), style)
                .draw(target)
                .ok();

            // Row 3: RSSI + SNR (compact to fit 21 chars)
            buf.clear();
            match (status.last_rssi, status.last_snr) {
                (Some(rssi), Some(snr)) => {
                    let _ = write!(buf, "{}dBm  SNR:{}dB", rssi, snr);
                }
                (Some(rssi), None) => {
                    let _ = write!(buf, "{}dBm", rssi);
                }
                _ => {
                    let _ = write!(buf, "No signal");
                }
            }
            Text::new(&buf, Point::new(0, FONT_H * 4 - 1), style)
                .draw(target)
                .ok();

            // Separator line (moved down to give RSSI/SNR breathing room)
            Line::new(Point::new(0, SEP_Y), Point::new(W - 1, SEP_Y))
                .into_styled(PrimitiveStyle::with_stroke(BinaryColor::On, 1))
                .draw(target)
                .ok();

            // RSSI sparkline (TX slots shown as dotted bars)
            rssi_sparkline(target, rssi_history, tx_history, rssi_count);
        }
        None => {
            let title_style = MonoTextStyle::new(&FONT_9X15_BOLD, BinaryColor::On);
            Text::with_alignment(
                "DongLoRa",
                Point::new(W / 2, 24),
                title_style,
                Alignment::Center,
            )
            .draw(target)
            .ok();
            Text::with_alignment(version, Point::new(W / 2, 38), style, Alignment::Center)
                .draw(target)
                .ok();
            Text::with_alignment(board_name, Point::new(W / 2, 50), style, Alignment::Center)
                .draw(target)
                .ok();
            Text::with_alignment(
                "Waiting for host...",
                Point::new(W / 2, 63),
                style,
                Alignment::Center,
            )
            .draw(target)
            .ok();
        }
    }
}

/// Render the RSSI history as a bar-chart sparkline.
///
/// Each bar represents one time slot. The display task advances the
/// slot index on a fixed timer, so each bar covers a constant duration
/// regardless of packet rate. RX slots draw solid bars; TX slots draw
/// dotted bars (alternating pixel rows). TX takes precedence if both
/// occurred in the same slot.
fn rssi_sparkline(
    target: &mut impl DrawTarget<Color = BinaryColor>,
    history: &[i16; RSSI_HISTORY_LEN],
    tx_history: &[bool; RSSI_HISTORY_LEN],
    count: usize,
) {
    if count == 0 {
        return;
    }

    let n = count.min(RSSI_HISTORY_LEN);
    let fill = PrimitiveStyle::with_fill(BinaryColor::On);

    for i in 0..n {
        let idx = if count <= RSSI_HISTORY_LEN {
            i
        } else {
            (count - RSSI_HISTORY_LEN + i) % RSSI_HISTORY_LEN
        };
        let is_tx = tx_history[idx];
        let rssi = history[idx];

        // TX slots with no RSSI: show a short fixed-height dotted bar
        let bar_h = if rssi <= RSSI_MIN {
            if is_tx {
                SPARK_H / 3 // small marker for TX-only slots
            } else {
                continue; // empty slot
            }
        } else {
            let clamped = rssi.clamp(RSSI_MIN, RSSI_MAX);
            ((clamped - RSSI_MIN) as i32 * SPARK_H) / (RSSI_MAX - RSSI_MIN) as i32
        };
        if bar_h == 0 {
            continue;
        }

        let x = (RSSI_HISTORY_LEN - n + i) as i32 * 2;
        let y = SPARK_TOP + SPARK_H - bar_h;

        if is_tx {
            // Dotted bar: draw every other pixel row
            for row in 0..bar_h {
                if row % 2 == 0 {
                    Rectangle::new(Point::new(x, y + row), Size::new(2, 1))
                        .into_styled(fill)
                        .draw(target)
                        .ok();
                }
            }
        } else {
            // Solid bar for RX
            Rectangle::new(Point::new(x, y), Size::new(2, bar_h as u32))
                .into_styled(fill)
                .draw(target)
                .ok();
        }
    }
}

/// Clear the display (display-off state).
pub fn blank(target: &mut impl DrawTarget<Color = BinaryColor>) {
    let _ = target.clear(BinaryColor::Off);
}

