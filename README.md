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

| Cog                   | Description |
| :-------------------- | :---------- |
| [avatar](#avatar)     | Returns a user's avatar as attachment |
| [kira](#kira)         | Remind people to only post relevant links |
| [repolist](#repolist) | List all installed repos and their available cogs |
| [youtube](#youtube)   | Posts in a channel every time a new video is added to a YouTube channel |
| [ytdedup](#ytdedup)   | Remove duplicate YouTube links in specified channels |

---

## avatar
Returns a user's avatar as attachment.

### Command
| Command  | Description                                            |
| :------- | :----------------------------------------------------- |
| `avatar` | User: can be user mention, nickname, username, user ID |

## kira
Remind people to only post relevant links.

### Command
| Command    | Description                                               |
| :--------- | :-------------------------------------------------------- |
| `watch`    | Add a channel to be monitored                             |
| `unwatch`  | Remove a channel from the watchlist                       |
| `question` | Change the question the sender will be required to answer |
| `timeout`  | Set the timeout for questioning the sender                |
| `domain`   | Configure which domains to look out for*                  |

*) Domains are not configurable yet. The current domains are youtu.be, youtube.com, www.youtube.com, and music.youtube.com

## repolist
List all installed repos and their available cogs in one command.

### Command
| Command    |
| :--------- |
| `repolist` |

## youtube
Posts in a channel every time a new video is added to a YouTube channel.

Biggest advantages over `Tube`:

-   Fetch any YouTube feed only once per interval, independent of how many Discord channels are subscribed to it
-   Add YouTube channels or edit its options with almost any URL. No more fiddling around to get the Channel ID
-   Better reports on what YouTube channels are monitored and where they are posted

Please be aware that the "new" https://www.youtube.com/@channel.name URLs are not yet support by the upstream library `PyTube` used in this project. Please use any video URL from such channels until the upstream issue has been resolved.

### Guild Commands
| Command       | Description                                          | Alias(es) |
| :------------ | :--------------------------------------------------- | :-------- |
| `subscribe`   | Subscribe a Discord channel to a YouTube channel     | `s`, `sub` |
| `unsubscribe` | Unsubscribe a Discord channel from a YouTube channel | `u`, `unsub` |
| `list`        | List current subscriptions                           ||
| `custom`      | Add or remove a custom message for new videos        | `c`, `customize` |
| `mention`     | Add or remove a role @mention                        | `m`, `rolemention` |
| `embed`       | Toggles between embedded messages and linking videos ||
| `info`        | Provides information about a YouTube subscription    ||
| `maxpages`    | Set the limit on amount of pages being sent          ||

### Guild Commands for [Community Servers](https://support.discord.com/hc/articles/360047132851) only
| Command   | Description                     | Alias | Information |
| :-------- | :------------------------------ | :---- | :---------- |
| `publish` | Toggles publishing new messages | `p`   | [Announcement Channels!](https://support.discord.com/hc/articles/360032008192) |

### Bot Owner Commands
| Command    | Description |
| :--------- | :---------- |
| `demo`     | Send a demo message to the current channel |
| `infoall`  | Provides information about a YouTube subscription across servers |
| `listall`  | List current subscriptions across servers |
| `delete`   | Delete a YouTube channel from the configuration |
| `interval` | Set the interval in seconds at which to check for updates |
| `migrate`  | Import all subscriptions from the `Tube` cog |

### Credits
Thanks to [Caleb](https://gitlab.com/CrunchBangDev) for making [Tube](https://gitlab.com/CrunchBangDev/cbd-cogs/-/tree/master/Tube), which was the base of this cog.

## ytdedup
Remove duplicate YouTube links in specified channels.

### Commands
| Command        | Description                                              | Alias |
| :------------- | :------------------------------------------------------- | :---- |
| `watch`        | Add a channel to be watched                              | `w` |
| `unwatch`      | Remove a channel from the watchlist                      | `u` |
| `notify`       | Toggle between informing the sender and complete silence ||
| `history`      | Set the amount of days history is being kept and checked ||
