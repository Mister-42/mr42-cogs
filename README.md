# Installation

Here are the [Red](https://github.com/Cog-Creators/Red-DiscordBot) commands to add this repository (use your bot's prefix in place of `[p]`):
```
[p]load downloader
[p]repo add Mr42 https://github.com/Mister-42/mr42-cogs
```

You may be prompted to respond with "I agree" after that.


# Cogs

You can install individual cogs like this:
```
[p]cog install Mr42 [cog]
```

Just replace `[cog]` with the name of the cog you want to install.

## avatar

Returns a user's avatar as attachment.

### Command

| Prefix   | Option                                                 |
| -------- | ------------------------------------------------------ |
| `avatar` | User: can be user mention, nickname, username, user ID |


## youtube

Posts in a channel every time a new video is added to a YouTube channel.

Biggest advantages over `Tube`:
- Fetch any YouTube feed only once per interval, independent of how many Discord channels are subscribed to it
- Add YouTube channels or edit its settings with almost any URL. No more fiddling around to get the Channel ID

### Guild Commands

| Command      | Description                                            | Alias(es) |
| ------------ | ------------------------------------------------------ | --------- |
| `youtube`    | Call this cog                                          | `yt` |
| `sub`        | Subscribe a Discord channel to a YouTube channel       | `s`, `subscribe` |
| `unsub`      | Unsubscribe a Discord channel from a YouTube channel   | `u`, `unsubscribe` |
| `list`       | List current subscriptions                             ||
| `custom`     | Add or remove a custom message for new videos          | `c`, `customize` |
| `mention`    | Add or remove a role @mention in front of the message  | `m`, `rolemention` |
| `publish`    | Toggles publishing new messages                        | `p` |
| `info`       | Provides information about a YouTube subscription      ||
| `autodelete` | Toggles auto deleting the commands given to the plugin ||

### Bot Owner Commands

| Command    | Description |
| ---------- | ----------- |
| `interval` | Set the interval in seconds at which to check for updates |
| `migrate`  | Import all subscriptions from the `Tube` cog |

### Credits

Thanks to [Caleb](https://gitlab.com/CrunchBangDev) for making [Tube](https://gitlab.com/CrunchBangDev/cbd-cogs/-/tree/master/Tube), which was the base of this cog.
