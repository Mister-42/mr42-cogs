# youtube
Posts in a channel every time a new video is added to a YouTube channel.

Biggest advantages over `Tube`:

-   Fetch any YouTube feed only once per interval, independent of how many Discord channels are subscribed to it
-   Add YouTube channels or edit their options with almost any URL. No more manual fiddling around to get the Channel ID
-   Better reports on what YouTube channels are monitored and where they are posted

## Usage
This cog can be called as `[p]youtube` or with its alias `[p]yt`.

## Guild Commands
| Command       | Description                                          | Alias(es) |
| :------------ | :--------------------------------------------------- | :-------- |
| `subscribe`   | Subscribe a Discord channel to a YouTube channel     | `s`, `sub` |
| `unsubscribe` | Unsubscribe a Discord channel from a YouTube channel | `u`, `unsub` |
| `list`        | List current subscriptions                           ||
| `custom`      | Add or remove a custom message for new videos        | `c`, `customize` |
| `mention`     | Add or remove a role @mention                        | `m`, `rolemention` |
| `embed`       | Toggles between embedded messages and linking videos ||
| `info`        | Provides information about a YouTube subscription    ||
| `maxpages`    | Set a limit on amount of pages `list` will send      ||

## Guild Commands for [Community Servers](https://support.discord.com/hc/articles/360047132851) only
| Command   | Description                     | Alias | Information |
| :-------- | :------------------------------ | :---- | :---------- |
| `publish` | Toggles publishing new messages | `p`   | [Announcement Channels!](https://support.discord.com/hc/articles/360032008192) |

## Bot Owner Commands
| Command    | Description |
| :--------- | :---------- |
| `demo`     | Send a demo message to the current channel |
| `infoall`  | Provides information about a YouTube subscription across servers |
| `listall`  | List current subscriptions across servers |
| `delete`   | Delete a YouTube channel from the configuration |
| `interval` | Set the interval in seconds at which to check for updates |
| `migrate`  | Import all subscriptions from the `Tube` cog |

## Credits
Thanks to [Caleb](https://gitlab.com/CrunchBangDev) for making [Tube](https://gitlab.com/CrunchBangDev/cbd-cogs/-/tree/master/Tube), which was the base of this cog.
