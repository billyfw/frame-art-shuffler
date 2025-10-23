# Token Management and Multi-Device Usage

## Summary

Samsung Frame TV tokens are device-specific authentication credentials that enable pairing between a client (laptop, HA instance, etc.) and the TV.

## Key Points

✅ **Tokens are gitignored** - They're in `.gitignore` to prevent committing credentials  
✅ **Multi-device safe** - Each machine should pair independently  
✅ **No conflicts** - TVs support multiple simultaneous pairings  
✅ **No invalidation** - New pairings don't invalidate existing ones  

## How Tokens Work

### Token Storage
```
custom_components/frame_art_shuffler/tokens/
├── README.md              # Documentation (tracked in git)
└── 192.168.1.249.token    # Token file (gitignored)
```

### Token Format
- Named by TV IP address: `<IP_ADDRESS>.token`
- 8 bytes of binary data
- Created automatically on first authorization

### Authorization Process

1. **First connection**: TV shows authorization popup
2. **User approves**: Select "Allow" on TV remote  
3. **Token saved**: Library creates token file automatically
4. **Reuse**: Future connections use the token transparently

## Multi-Device Scenarios

### Scenario 1: Development Laptop + Home Assistant
```
Laptop:              192.168.1.249.token (pairing #1)
Home Assistant:      192.168.1.249.token (pairing #2)
```
- Both work simultaneously
- Each authorized independently
- No conflicts

### Scenario 2: Multiple Developers
```
Developer A laptop:  192.168.1.249.token (pairing #1)
Developer B laptop:  192.168.1.249.token (pairing #2)
Home Assistant:      192.168.1.249.token (pairing #3)
```
- Each developer authorizes on their machine
- Tokens are not shared (gitignored)
- All work independently

## Security Best Practices

❌ **Don't** commit tokens to git  
❌ **Don't** share tokens across machines  
❌ **Don't** manually copy tokens (just re-authorize)  

✅ **Do** let each machine pair independently  
✅ **Do** treat tokens as credentials  
✅ **Do** keep tokens gitignored  

## FAQs

**Q: Will authorizing on my laptop break Home Assistant?**  
A: No. Each pairing is independent.

**Q: Should I copy the token file to my laptop?**  
A: No. Just run the command and authorize when prompted.

**Q: How many devices can pair with one TV?**  
A: Samsung TVs support multiple pairings (exact limit unknown, but dozens should be fine).

**Q: What happens if I delete a token file?**  
A: Next connection will prompt for authorization again and create a new token.

**Q: Can I commit the tokens directory structure?**  
A: Yes, the `README.md` is tracked, but `.token` files are gitignored.

## Implementation

### .gitignore Entry
```gitignore
# Samsung Frame TV tokens (device-specific authentication)
# Each machine should pair independently with the TV
custom_components/frame_art_shuffler/tokens/*.token
```

This ignores all `.token` files but allows tracking the directory and README.
