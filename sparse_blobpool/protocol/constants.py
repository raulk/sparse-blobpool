"""Protocol constants for EIP-8070 sparse blobpool."""

# Cell and blob constants
CELL_SIZE = 2048  # bytes per cell
CELLS_PER_BLOB = 128  # columns per extended blob
CELLS_PER_EXT_BLOB = 128  # alias for clarity (same as CELLS_PER_BLOB)

# Reconstruction threshold
RECONSTRUCTION_THRESHOLD = 64  # cells required for Reed-Solomon decoding

# Maximum blobs per transaction
MAX_BLOBS_PER_TX = 6

# Cell mask constants
ALL_ONES = (1 << CELLS_PER_BLOB) - 1  # uint128 with all bits set (full availability)

# Message IDs (eth/71 protocol)
MSG_NEW_POOLED_TX_HASHES = 0x08
MSG_GET_POOLED_TRANSACTIONS = 0x09
MSG_POOLED_TRANSACTIONS = 0x0A
MSG_GET_CELLS = 0x12
MSG_CELLS = 0x13

# Base message overhead (request_id + message type)
MESSAGE_OVERHEAD = 8  # bytes
