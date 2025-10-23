# Samsung Frame TV Tokens

This directory stores authentication tokens for paired Samsung Frame TVs.

## Token Behavior

- **Format**: `<IP_ADDRESS>.token` (e.g., `192.168.1.249.token`)
- **Per-device pairing**: Each token represents a pairing between this client and a TV
- **Multiple pairings supported**: TVs can have multiple paired clients simultaneously
- **Not shared across machines**: Each development machine and Home Assistant instance should pair independently

## Security

Token files are gitignored and should **not** be committed to version control:
- They are authentication credentials
- They are device/machine specific
- Multiple pairings don't conflict

## Authorization Flow

1. First time connecting to a TV, the library will request authorization
2. A popup appears on the TV asking to allow/deny the connection
3. Once allowed, a token is saved in this directory
4. Subsequent connections reuse the token automatically

## Home Assistant

When deployed in Home Assistant, this directory will be located at:
```
/config/custom_components/frame_art_shuffler/tokens/
```

Each Home Assistant instance maintains its own tokens independently.
