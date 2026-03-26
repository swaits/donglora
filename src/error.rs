/// Radio hardware errors.
#[allow(dead_code)]
#[derive(Debug, defmt::Format)]
pub enum RadioError {
    InitFailed,
    TxTimeout,
    InvalidConfig,
}

/// USB protocol framing errors.
#[allow(dead_code)]
#[derive(Debug, defmt::Format)]
pub enum ProtocolError {
    DeserializeFailed,
    BufferOverflow,
}
