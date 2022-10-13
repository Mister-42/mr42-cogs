# Installation

Here are the [Red](https://github.com/Cog-Creators/Red-DiscordBot) commands to add this repository. Replace `[p]` with you bot's prefix:
```text
[p]load downloader
[p]repo add mr42-cogs https://github.com/Mister-42/mr42-cogs
```

You may be prompted to respond with "I agree" after that.

# Cogs

You can install individual cogs with the following command. Replace `[cog]` with the name of the cog you want to install.
```text
[p]cog install mr42-cogs [cog]
```

| Cog                 | Description |
| :------------------ | :---------- |
| [avatar](#avatar)   | Returns a user's avatar as attachment |
| [youtube](#youtube) | Posts in a channel every time a new video is added to a YouTube channel |

---

## avatar

Returns a user's avatar as attachment.

### Command

| Prefix   | Option                                                 |
| :------- | :----------------------------------------------------- |
| `avatar` | User: can be user mention, nickname, username, user ID |

## youtube

Posts in a channel every time a new video is added to a YouTube channel.

Biggest advantages over `Tube`:
-  Fetch any YouTube feed only once per interval, independent of how many Discord channels are subscribed to it
-  Add YouTube channels or edit its options with almost any URL. No more fiddling around to get the Channel ID

### Guild Commands

| Command      | Description                                           | Alias(es) |
| :----------- | :---------------------------------------------------- | :-------- |
| `youtube`    | Call this cog                                         | `yt` |
| `sub`        | Subscribe a Discord channel to a YouTube channel      | `s`, `subscribe` |
| `unsub`      | Unsubscribe a Discord channel from a YouTube channel  | `u`, `unsubscribe` |
| `list`       | List current subscriptions                            ||
| `custom`     | Add or remove a custom message for new videos         | `c`, `customize` |
| `mention`    | Add or remove a role @mention in front of the message | `m`, `rolemention` |
| `publish`    | Toggles publishing new messages                       | `p` |
| `info`       | Provides information about a YouTube subscription     ||

### Bot Owner Commands

| Command    | Description |
| :--------- | :---------- |
| `infoall`  | Provides information about a YouTube subscription across servers |
| `interval` | Set the interval in seconds at which to check for updates |
| `listall`  | List current subscriptions across servers |
| `migrate`  | Import all subscriptions from the `Tube` cog |

### Credits

Thanks to [Caleb](https://gitlab.com/CrunchBangDev) for making [Tube](https://gitlab.com/CrunchBangDev/cbd-cogs/-/tree/master/Tube), which was the base of this cog.
