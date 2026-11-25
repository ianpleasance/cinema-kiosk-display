# Installing the Foyer Kiosk on a Raspberry Pi 3B+ or later

This guide takes you from a blank SD card to a screen that shows the cinema's schedule by itself,
starts on its own after a power cut, and has its image folders shared on your network. It assumes the
Pi has **no keyboard or screen** while you set it up ("headless"): everything is done from your own
computer over the network. Allow about an hour the first time.

Once it's running, [USAGE.md](USAGE.md) explains how to change settings, add your own images and
look after it.

Contents

1. [What you need](#1-what-you-need)
2. [Flash the SD card](#2-flash-the-sd-card)
3. [First boot and login](#3-first-boot-and-login)
4. [Set up the base system](#4-set-up-the-base-system)
5. [Wi-Fi: add a backup network](#5-wi-fi-add-a-backup-network)
6. [Install Docker](#6-install-docker)
7. [Get the code](#7-get-the-code)
8. [Share the image folders on the network](#8-share-the-image-folders-on-the-network)
9. [Configure it](#9-configure-it)
10. [Build and run](#10-build-and-run)
11. [Check it works, then test a reboot](#11-check-it-works-then-test-a-reboot)
12. [Optional: reach the Pi from anywhere with Tailscale](#12-optional-reach-the-pi-from-anywhere-with-tailscale)
13. [Updating to a new version](#13-updating-to-a-new-version)
14. [If something goes wrong during installation](#14-if-something-goes-wrong-during-installation)
15. [Maintenance, backups and removal](#15-maintenance-backups-and-removal)

**Conventions.**

- **[computer]** means: run this on your own laptop or PC.
- **[pi]** means: run this on the Pi, in an SSH session logged in as the `cinema` user.
- Names used below, which you can change: hostname `foyer-kiosk`, user `cinema`, project folder
  `/home/cinema/empire-kiosk` (the `.md` guides live there) and the application folder inside it,
  `/home/cinema/empire-kiosk/cinema-kiosk`, where `docker-compose.yml` and `.env` are.
- Only one account is used. `cinema` can use `sudo` (without a password, set up in step 4) and is the account
  that runs Docker and owns all the files, and the same name and password are used for the network shares.

---

## 1. What you need

- **A Raspberry Pi 3B+, 4 or 5** (or a Pi 3B, 3A+, 400 or 500), with the official power supply.
  A 3B+ has 1 GB of memory, which is enough. A weak supply causes odd behaviour (slide stutter, random
  reboots), so don't skimp.
- **A microSD card**, 16 GB or larger, from a reputable brand. Cards in a 24/7 kiosk wear out.
- **A screen with HDMI**, and the right cable: a standard HDMI cable for the Pi 3, or micro-HDMI to
  HDMI for the Pi 4 and 5.
- **Network**: Wi-Fi with an ordinary password, or Ethernet (more reliable, if there is a socket
  nearby). Wi-Fi that needs a login page in a browser ("captive portal") or a company-style login
  (802.1X) won't work for an unattended device. The Pi 3B+ and Pi 4/5 handle both 2.4 GHz and 5 GHz Wi-Fi.
- **A computer** to flash the card and to connect to the Pi, with an SD card reader.
- **A copy of this project**: the `.tar.gz` file it came in, or your Git repository.
- Your Wi-Fi network name (SSID) and password, plus those of a backup network if you have one.

> **Not supported: the original Raspberry Pi Zero, Zero W and Pi 1.** They have an old ARMv6 processor.
> Docker does not run on them (its programs stop with `Illegal instruction`), and they are far too slow
> for a 1080p fading slideshow. The **Zero 2 W** is a different, newer board and is not covered by this
> guide (512 MB of memory is tight). Check your board before you start: on the Pi run
> `tr -d '\0' < /proc/device-tree/model; echo` (it should say *Pi 3*, *Pi 4* or *Pi 5*) and `uname -m`
> (it must **not** say `armv6l`).

## 2. Flash the SD card

This step puts the operating system on the card **and**, so that you never need a keyboard or screen,
sets the hostname, user, Wi-Fi and SSH before the Pi first starts.

1. **[computer]** Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and open it.
2. Choose your **Device** (Pi model), then the **Operating system**:
   **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)**. "Lite" has no desktop, which is what we
   want: the kiosk takes over the screen itself. Don't use a desktop version. The 64-bit version is
   the one Docker supports best, and it runs fine on a 3B+, 4 or 5. (The 32-bit version also exists, but
   Docker's support for it is ending, so don't choose it.)
3. Choose your **Storage** (the SD card). Check the size to be sure it's the right drive: everything on
   it will be erased.
4. Fill in the **customisation** settings. Their layout differs a little between Imager versions
   (newer ones have tabs such as Localisation, User, Wi-Fi and Remote access; older ones have an
   "Edit settings" window), but the same things are asked for:

   | Setting | What to enter |
   |---|---|
   | **Hostname** | `foyer-kiosk` (you'll reach the Pi as `foyer-kiosk.local`) |
   | **Username** | `cinema` |
   | **Password** | a strong password for `cinema`. You'll use it to log in and for the network shares. |
   | **Wi-Fi** | your network's name and password, and the **Wi-Fi country** (`GB` for the UK). Tick "hidden network" only if it is hidden. Skip Wi-Fi if you'll use Ethernet. |
   | **Locale** | time zone `Europe/London`, keyboard layout `gb` |
   | **SSH** | **enable** it. Choose password login, or paste your public key if you have one (better; see [step 3](#3-first-boot-and-login)). |

   You can only enter one Wi-Fi network here. The backup network is added in [step 5](#5-wi-fi-add-a-backup-network).
5. Write the card. Wait for it to finish and verify, then remove it.
6. Put the card in the Pi, connect the screen (and the network cable if you use one), and power it on.
   The first boot takes a minute or two, because it expands the
   filesystem and sets everything up.

**If you skipped the customisation settings**, or they weren't applied (Imager sometimes doesn't apply
all of them), you can set up SSH by hand: before putting the card in the Pi, open the card's small
`bootfs` drive on your computer and

- create an **empty file called `ssh`** (no extension), and
- create a file called `userconf.txt` with a single line `cinema:` followed immediately by a password
  hash. Make the hash on your computer with `openssl passwd -6` (it asks for the password), or on
  Windows use Imager's settings instead.

Wi-Fi is much easier to set through Imager. Otherwise connect the Pi by Ethernet, log in over SSH,
and add the Wi-Fi with `nmcli` as in [step 5](#5-wi-fi-add-a-backup-network). (Without Imager you can also
plug a screen and keyboard into the Pi and run `sudo raspi-config` to set Wi-Fi and enable SSH.)

## 3. First boot and login

1. **[computer]** After a couple of minutes, check the Pi is on the network:

   ```bash
   ping foyer-kiosk.local
   ```

   If `.local` names don't work on your computer, look up the Pi's IP address in your router's list of
   connected devices and use that everywhere instead of `foyer-kiosk.local`. It's worth giving the
   Pi a **reserved (fixed) address** in the router, so the address never changes.

2. **[computer]** Log in:

   ```bash
   ssh cinema@foyer-kiosk.local
   ```

   Answer `yes` to the question about the host's fingerprint, then give the password. You should get a
   prompt like `cinema@foyer-kiosk:~ $`. Everything marked **[pi]** from here on is typed there.

3. **[computer]** Optional but recommended: log in with an SSH key instead of a password. If you don't
   have a key, make one with `ssh-keygen -t ed25519`, then:

   ```bash
   ssh-copy-id cinema@foyer-kiosk.local
   ssh cinema@foyer-kiosk.local         # should log you in without asking for the password
   ```

   Once the key works you can turn password logins off (**[pi]**), keeping your first session open
   while you test a second login, so a mistake can't lock you out:

   ```bash
   echo 'PasswordAuthentication no' | sudo tee /etc/ssh/sshd_config.d/10-no-passwords.conf
   sudo systemctl reload ssh
   ```

   The network shares in [step 8](#8-share-the-image-folders-on-the-network) have their own password and
   aren't affected.

If you can't connect, see [step 14](#14-if-something-goes-wrong-during-installation).

## 4. Set up the base system

All **[pi]**. Each of these is quick; the reboot at the end applies them together.

**Let `cinema` use `sudo` without typing a password.** Raspberry Pi OS often sets this up already for the
first user; this makes sure, and it saves typing the password for every command in this guide and for
scripted maintenance. Keep your SSH session open until the check passes:

```bash
echo 'cinema ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/010_cinema-nopasswd
sudo chmod 0440 /etc/sudoers.d/010_cinema-nopasswd
sudo visudo -cf /etc/sudoers.d/010_cinema-nopasswd      # must say: parsed OK
sudo -k; sudo -n true && echo "passwordless sudo works"
```

If the `visudo` check reports an error, delete the file (`sudo rm /etc/sudoers.d/010_cinema-nopasswd`) and
try again; a broken sudoers file can lock you out of `sudo`. Note this makes anyone who can log in as
`cinema` an administrator without a further password, which is already true of Docker group members
(step 6), so protect the login: use an SSH key and a strong password, and don't expose SSH to the internet.

**Update the system and install tools:**

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git
```

**Time zone and Wi-Fi country** (the Imager settings should have done these; this makes sure):

```bash
sudo timedatectl set-timezone Europe/London
sudo raspi-config nonint do_wifi_country GB
timedatectl                       # "System clock synchronized: yes" once it's online
```

Dates and times on the slides depend on the clock, so check the time shown is right. The containers use
their own `TZ` setting (in `.env`), which should agree with this.

**Stop Wi-Fi power saving.** Pi Wi-Fi can drop out when power saving is on, which is a nuisance for a
device nobody touches. This turns it off for all current and future Wi-Fi connections:

```bash
sudo mkdir -p /etc/NetworkManager/conf.d
printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf
```

**Display settings.** The kiosk draws straight to the screen with the Pi's graphics driver (KMS), which
is on by default. Check, and **don't install a desktop** or switch the Pi to log in to one: a desktop
takes over the screen and the kiosk can't use it.

```bash
grep vc4-kms /boot/firmware/config.txt        # should show: dtoverlay=vc4-kms-v3d
```

Strongly recommended on TVs and big displays, which often offer 4K: force 1080p so the Pi isn't
scaling to a bigger picture for no benefit, and stop the text console switching the screen off.
`cmdline.txt` must stay **one single line**, so this adds to the end of it. Run it **once**:

```bash
sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
sudo sed -i '1 s/$/ video=HDMI-A-1:1920x1080@60 consoleblank=0/' /boot/firmware/cmdline.txt
cat /boot/firmware/cmdline.txt                # still one line, ending in the two new settings
```

`HDMI-A-1` is the first HDMI port (the only one on a Pi 3, and the one nearest the power connector on a
Pi 4 or 5). Use `HDMI-A-2` if the screen is on the second port. If the Pi won't start afterwards,
put the card in your computer and restore `cmdline.txt.bak` over `cmdline.txt`.

**Hardware watchdog (recommended).** The Pi has a hardware watchdog: a timer that resets the board if the
operating system stops responding. It is built into the kernel but **switched off until systemd is told to
use it**. With it on, a frozen Pi restarts itself within seconds instead of staying stuck until someone
notices. (Docker already restarts a crashed *container*; this covers the whole Pi locking up.) The longest
timeout the Pi's watchdog supports is about 15 seconds.

```bash
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/90-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=10s
RebootWatchdogSec=15s
EOF
```

`RuntimeWatchdogSec` is how long the system may go silent before the reset; `RebootWatchdogSec` does
the same for a shutdown or reboot that gets stuck. (Some Raspberry Pi OS releases ship a file such as
`40-rpi-enable-watchdog.conf` in `/usr/lib/systemd/system.conf.d/`; the file above is read later, so its
values win.) It is checked after the reboot below.

**If the Docker build is "Killed" (a 1 GB Pi 3B+ only, unlikely).** The Pi already has compressed swap in
memory (zram, from the `rpi-swap` package; check with `free -h`). Only if the build in
[step 10](#10-build-and-run) is "Killed" or the Pi freezes, add a real 1 GB swap file (this wears the SD card a
little, so it's a fix for a problem rather than a default):

```bash
sudo mkdir -p /etc/rpi/swap.conf.d
sudo tee /etc/rpi/swap.conf.d/80-swapfile.conf <<'EOT'
[Main]
Mechanism=swapfile

[File]
FixedSizeMiB=1024
EOT
sudo reboot
```

After the reboot, `cat /proc/swaps` should list `/var/swap`. To go back to the default, delete that file
and reboot again.

**Optional: automatic security updates.** To have the Pi install Debian's security fixes by itself:
`sudo apt install -y unattended-upgrades`, then `sudo dpkg-reconfigure -plow unattended-upgrades` and
answer Yes. It never reboots on its own; do that yourself now and then (see [step 15](#15-maintenance-backups-and-removal)).

**Reboot**, then log in again and check the watchdog and the display mode took effect:

```bash
sudo reboot
```

```bash
# [pi], after logging back in
sudo dmesg | grep -i watchdog                       # "Broadcom BCM2835 watchdog timer"
systemctl show -p RuntimeWatchdogUSec               # should say 10s, not 0
cat /proc/cmdline                                   # should include video=HDMI-A-1:1920x1080@60
```

Optional test of the watchdog, which deliberately crashes the Pi (it should restart by itself within
about 15 seconds; log in again afterwards):

```bash
echo c | sudo tee /proc/sysrq-trigger
```

If it just sits there, the watchdog isn't active: re-check the file above. To turn it off, delete
`/etc/systemd/system.conf.d/90-watchdog.conf` and reboot. A watchdog can't help if the Pi has lost power;
it only recovers a frozen one.

## 5. Wi-Fi: add a backup network

Raspberry Pi OS manages networks with **NetworkManager**, which remembers any number of Wi-Fi networks
and joins whichever is in range, preferring the one with the highest **priority**. Imager set up only
your first network, so add the backup yourself. This is useful if the cinema's Wi-Fi sometimes fails, if
the Pi will be used at more than one site, or if you want a phone hotspot as a last resort.

**[pi]** First see what's saved and give the main network a priority. Imager's network is usually named
`preconfigured` (the exact name appears in the list):

```bash
nmcli connection show
sudo nmcli connection modify "preconfigured" connection.autoconnect yes connection.autoconnect-priority 30
```

Then add the backup (the `con-name` is just a label for you):

```bash
sudo nmcli connection add type wifi con-name "Cinema-Backup" ssid "BackupNetworkName" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "backup-password" \
  connection.autoconnect yes connection.autoconnect-priority 10
```

- The **higher** priority number is tried first. If that network isn't in range or drops, the Pi moves on
  to the next saved one, and goes back when the preferred one returns.
- A network doesn't need to be in range when you add it, so you can set up another site's Wi-Fi in advance.
- For a hidden network add `802-11-wireless.hidden yes` to the command. Add as many networks as you like.
- A network cable is used in preference to Wi-Fi whenever it's plugged in.

Useful commands:

```bash
nmcli connection show                          # saved networks and their names
nmcli device wifi list                         # networks in range right now
nmcli -t -f active,ssid dev wifi | grep ^yes   # which one am I connected to?
sudo nmcli connection modify "Cinema-Backup" connection.autoconnect-priority 5    # change priority
sudo nmcli connection modify "Cinema-Backup" wifi-sec.psk "new-password"          # change a password
sudo nmcli connection delete "Cinema-Backup"                                       # forget a network
```

To test the fallback, switch off the main network's router (or move its priority below the backup's)
and watch `nmcli -t -f active,ssid dev wifi | grep ^yes` for a minute or two. Careful when changing
Wi-Fi over a Wi-Fi SSH session: if you break the network you're connected through, you lose the
connection. An Ethernet cable, or a keyboard on the Pi, is a good way back in.

## 6. Install Docker

First check the board and the operating system (**[pi]**):

```bash
tr -d '\0' < /proc/device-tree/model; echo   # e.g. "Raspberry Pi 3 Model B Plus Rev 1.3"
uname -m                             # aarch64 is what you want; armv6l means Docker will not work
dpkg --print-architecture            # arm64 = 64-bit (good)
```

If `uname -m` says `armv6l`, **stop**: this is an original Pi Zero, Zero W or Pi 1, which Docker does not
support. If `dpkg --print-architecture` says `armhf` (a 32-bit install), re-flash with the **64-bit** Lite
image ([step 2](#2-flash-the-sd-card)): Docker is ending its support for 32-bit Raspberry Pi OS.

Use Docker's official install script. It adds Docker's repository, so you get updates through the normal
`apt` upgrades. Downloading it first lets you read it before running it:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
less get-docker.sh                 # optional: read it (press q to quit)
sudo sh get-docker.sh
rm get-docker.sh
```

Check that it installed, with the Compose plugin, and that it starts at boot:

```bash
docker --version
docker compose version
sudo systemctl enable --now docker containerd
```

Now allow the `cinema` user to run Docker without `sudo`, and log in again for it to take effect:

```bash
sudo usermod -aG docker cinema
exit
```

**[computer]** `ssh cinema@foyer-kiosk.local` again, then **[pi]**:

```bash
docker ps
```

An empty table (just the column headings) means all is well. `permission denied` means the group change
hasn't applied: log out and in again.

> **Note:** membership of the `docker` group is effectively root access to the Pi, because Docker can mount
> any part of the system. Treat the `cinema` password and SSH keys with the same care as an administrator's.

## 7. Get the code

**[pi]** From Git (replace the address with your repository's):

```bash
cd ~
git clone <your-repo-url> empire-kiosk
cd empire-kiosk/cinema-kiosk
```

For a private repository, make a read-only **deploy key** for the Pi: run
`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""`, show it with `cat ~/.ssh/id_ed25519.pub`, add it under
your repository's deploy keys, then clone using the `git@...` address.

**Or from a tarball** instead of Git:

```bash
# [computer]
scp cinema-kiosk.tar.gz cinema@foyer-kiosk.local:~

# [pi]
mkdir -p ~/empire-kiosk && tar xzf ~/empire-kiosk/cinema-kiosk.tar.gz -C ~/empire-kiosk
cd ~/empire-kiosk/cinema-kiosk
```

The tarball puts the guides (`README.md`, `INSTALL.md`, `USAGE.md`, `CHANGELOG.md`) in `~/empire-kiosk`
and everything else in `~/empire-kiosk/cinema-kiosk`.

Everything from here is run from inside `~/empire-kiosk/cinema-kiosk`. Check that the folders the containers use are
there, and that the Pi's `cinema` user has the user ID the containers expect:

```bash
ls
id cinema                       # should start: uid=1000(cinema) gid=1000(cinema)
```

You should see `slides`, `static`, `logs`, `video` and `fonts`. If `id cinema` shows a different number
than 1000, edit the `user: "1000:1000"` line in `docker-compose.yml` to match, so that the updater can
write to the folders (and so you can change what it writes through the network share).

## 8. Share the image folders on the network

This makes two folders on the Pi appear as ordinary network folders on your PC or Mac, so staff can drop
in an image or tidy up the slides without using SSH. It uses **Samba** (the standard Windows-compatible
file sharing for Linux) and the same `cinema` user name and password.

| Share | Folder on the Pi | What it's for |
|---|---|---|
| `static` | `~/empire-kiosk/cinema-kiosk/static` | **Your own images** (offers, house rules, sponsors). Add and remove them here. |
| `slides` | `~/empire-kiosk/cinema-kiosk/slides` | The **rendered film slides** made by the updater (read it, or remove a slide you don't want). |

1. **[pi]** Install Samba. If it asks about WINS settings from DHCP, answer **No**:

   ```bash
   sudo apt install -y samba
   ```

2. **[pi]** Give `cinema` a Samba password. Samba keeps its own password list, separate from the login
   password; use the **same** password so there's only one to remember:

   ```bash
   sudo smbpasswd -a cinema
   ```

3. **[pi]** Add the two shares to Samba's configuration. (Copy it exactly. If you used another user name
   or folder, change `cinema` and the paths.)

   ```bash
   sudo tee -a /etc/samba/smb.conf <<'EOF'

   [static]
      comment = Cinema kiosk - your own images
      path = /home/cinema/empire-kiosk/cinema-kiosk/static
      browseable = yes
      read only = no
      valid users = cinema
      force user = cinema
      force group = cinema
      create mask = 0664
      directory mask = 0775

   [slides]
      comment = Cinema kiosk - rendered slides
      path = /home/cinema/empire-kiosk/cinema-kiosk/slides
      browseable = yes
      read only = no
      valid users = cinema
      force user = cinema
      force group = cinema
      create mask = 0664
      directory mask = 0775
   EOF
   ```

   Optionally, a third, **read-only** share for the slideshow video (see `VIDEO_MODE` in
   [USAGE.md](USAGE.md#slideshow-video)): the same lines with the heading `[video]`, `path =
   /home/cinema/empire-kiosk/cinema-kiosk/video` and `read only = yes`.

4. **[pi]** Check the file for mistakes, then start Samba and have it start at every boot:

   ```bash
   testparm -s                                  # no errors; the [static] and [slides] shares are listed
   sudo systemctl enable --now smbd nmbd
   sudo systemctl restart smbd nmbd
   ```

5. **[computer]** Connect, and log in as user `cinema` with the Samba password when asked:

   | From | How |
   |---|---|
   | **Windows** | File Explorer address bar: `\\foyer-kiosk\static` (or `\\<the Pi's IP address>\static`). To keep it, right-click the folder and choose Map network drive. |
   | **macOS** | Finder, Go menu, Connect to Server (Cmd+K): `smb://foyer-kiosk.local/static` |
   | **Linux** | File manager, Other Locations, Connect to Server: `smb://foyer-kiosk.local/static` |

   The names work as long as the Pi is reachable by its hostname; the IP address always works.

How it behaves:

- Images you copy into `static` are shown at the next slide change, with no restart. See
  [USAGE.md](USAGE.md#your-own-images-static) for naming, sizes and ordering.
- In `slides`, look in `current/`. Deleting a slide there removes it from the screen immediately, but the
  updater **rebuilds that folder at its next refresh**, so changes there don't last. Anything you want to
  keep goes in `static`. The `archive/` folder inside `slides` holds slides of films that have gone.
- The shares are for your own network only. Don't forward Samba's ports (139, 445) on the router. For
  remote access use [Tailscale](#12-optional-reach-the-pi-from-anywhere-with-tailscale).
- Only the `cinema` user can open them (`valid users`). To change the Samba password later:
  `sudo smbpasswd cinema`.

## 9. Configure it

All settings are in one file, `.env`. It's a hidden file (its name starts with a dot); `ls -a` lists it.

**[pi]**, in `~/empire-kiosk/cinema-kiosk`:

```bash
nano .env
```

The defaults work as they are. Decisions you'll probably want to make now:

- `TIME_FORMAT`: `12h` (7:30pm) or `24h` (19:30).
- `RUN_AT`: when the schedule refreshes (default `03:30`). You can give several times, such as
  `RUN_AT=0330,1230,1530,2030`, so a matinee or evening show disappears soon after it has started.
  **The Pi must be switched on at those times.** If it's powered off overnight, leave out the overnight time.
  A refresh missed because the Pi was off is not made up until the next scheduled time (a brand-new
  install is the exception: it updates immediately).
- `DAYS_AHEAD`: `0` shows every event on the schedule; a number such as `14` shows only today and the next 14 days.
- `SAVE_POSTERS`: `1` also shows each original poster before its info slide; `0` shows only the info slides.
- `VIDEO_MODE`: leave `none` unless you want a slideshow mp4 (`plain`, `fade` or `both`).
- Colours and text sizes, if you want to change the look. Colours are hex **without** a `#`, such as `FFD700`.

Every setting is described in [USAGE.md](USAGE.md#settings-reference) and in a comment above it in the
file. Save with Ctrl+O, Enter, then exit with Ctrl+X.

## 10. Build and run

**[pi]** Build the images and start both containers in the background:

```bash
docker compose up -d --build
```

The first build downloads base images and packages and takes several minutes on a Pi 4/5 (a little longer on a 3B+). Then watch what the updater is doing:

```bash
docker compose logs -f
```

(Ctrl+C stops following; the containers carry on.) A healthy first start looks like:

```
updater-1  | ... INFO Empire kiosk updater v1.0.0 starting (updates at 03:30 Europe/London)
updater-1  | ... INFO Listing shows 43 films
updater-1  | ... INFO (1/43) Retrieving Ghosts: Possession of Button House
updater-1  | ... INFO (1/43) Done: 2 dates: Sat 21 Nov 7:30pm; Wed 25 Nov 2:30pm
...
updater-1  | ... INFO Update complete: 43 films, 86 files
display-1  | ... INFO Empire kiosk display v1.0.0 starting
display-1  | ... INFO Display 1920x1080 (gpu)
```

The screen stays black (or shows just your `static` images) until the first update finishes, which takes
a few minutes. Then the slideshow begins.

Both containers are set to `restart: unless-stopped` and Docker starts at boot, so **nothing else is
needed to make it start automatically** after a power cut.

## 11. Check it works, then test a reboot

**[pi]**

```bash
docker compose ps                              # both services should show "Up"
ls slides/current                              # the slide files
tail -n 20 logs/updater.log                    # the updater's own log
```

Look at the screen: slides should be fading through. Also check the shares from your computer
([step 8](#8-share-the-image-folders-on-the-network)): you should see the `slides/current` files, and be able to
copy a test image into `static`, which should appear on screen within a few slides. Delete the test image after.

Now check that a power cut behaves:

```bash
sudo reboot
```

After a minute or two the slideshow should be back on its own, without anyone
logging in. If it isn't, see [step 14](#14-if-something-goes-wrong-during-installation) and the troubleshooting
section of [USAGE.md](USAGE.md#logs-and-troubleshooting).

## 12. Optional: reach the Pi from anywhere with Tailscale

[Tailscale](https://tailscale.com/) gives the Pi a private address that works from your own devices over
the internet, without opening anything on the cinema's router. It's handy for fixing the kiosk from home,
and it means the SSH and file shares can be used remotely without exposing them. It runs on the Pi itself
(not in Docker), and the free personal plan is enough.

1. Create a Tailscale account, and install Tailscale on your own computer or phone.
2. **[pi]** Install it on the Pi, then join it to your account:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   `tailscale up` prints a web address. Open it on any device, sign in, and approve the Pi.
3. In the Tailscale **admin console** (Machines page), find the Pi and choose **Disable key expiry**.
   Otherwise it drops off your network after a few months and someone has to go on site.
4. With Tailscale running on your own device, connect to the Pi's Tailscale name or its `100.x.y.z`
   address: `ssh cinema@foyer-kiosk`, or `\\foyer-kiosk\static` for the file share.

To let Tailscale handle SSH logins itself (no keys or passwords to manage): `sudo tailscale set --ssh`.
To check the connection: `tailscale status`. To disconnect: `sudo tailscale down`. Only devices signed in
to *your* Tailscale account can reach the Pi.

## 13. Updating to a new version

Read the [CHANGELOG](CHANGELOG.md) first, then **[pi]**:

```bash
cd ~/empire-kiosk/cinema-kiosk
cat VERSION                                  # the version you have now
git pull --rebase --autostash                # your edits to .env are kept
docker compose up -d --build
docker compose exec updater python updater.py --once
```

Settings added in newer versions have built-in defaults, so your existing `.env` keeps working; copy any
new settings you want into it. If `git pull` reports a conflict in `.env`, keep your values and add the new
lines from the repository's copy. If you installed from a tarball, unpack the new one into a fresh folder,
copy your `.env`, your `static` images and your `fonts` across, and run the same `docker compose` commands there
(stop the old copy first with `docker compose down`).

To go back to an earlier version: `git checkout v1.0.0` (use the version's tag), then
`docker compose up -d --build`.

## 14. If something goes wrong during installation

Problems once it's running are covered in [USAGE.md](USAGE.md#logs-and-troubleshooting). For installation:

| Symptom | Likely cause and fix |
|---|---|
| **`ping foyer-kiosk.local` finds nothing** | Give it a few minutes (a first boot can be slow). Check the Pi's green light flickers, then look for it in the router's device list and use its IP address. If Wi-Fi was set up in Imager, check the password and country; try Ethernet. Windows computers without Bonjour may not resolve `.local`: use the IP address. |
| **`Connection refused` when running `ssh`** | SSH isn't enabled: re-flash with SSH ticked, or create the empty `ssh` file on `bootfs` ([step 2](#2-flash-the-sd-card)). |
| **`Permission denied` at the password** | A wrong password, or Imager's user settings weren't applied so there is no `cinema` user. Re-flash and check the settings, or use the `ssh` and `userconf.txt` method in [step 2](#2-flash-the-sd-card). |
| **Host key changed warning** | You've re-flashed a card with the same name. Run `ssh-keygen -R foyer-kiosk.local` on your computer, then connect again. |
| **Pi never joins the Wi-Fi** | Wrong password or Wi-Fi country, or a captive-portal network. Use Ethernet and fix it with `nmcli` ([step 5](#5-wi-fi-add-a-backup-network)). |
| **`Illegal instruction` when running `docker`** | The Pi has an ARMv6 processor (original Zero, Zero W or Pi 1), which Docker doesn't support. Confirm with `uname -m` (`armv6l`) and use a Pi 3B+, 4 or 5 instead. The same SD card works in the new board. |
| **`docker: permission denied`** | `cinema` isn't in the `docker` group yet, or you haven't logged in again since adding it ([step 6](#6-install-docker)). |
| **The build is "Killed" or the Pi freezes** | Out of memory: add swap ([step 4](#4-set-up-the-base-system)) and run the build again. |
| **Screen stays black but containers are "Up"** | Normal for the first few minutes until the first update completes. If it persists: `docker compose logs --tail 50`. If slides exist (`ls slides/current`) it's a display-driver problem: check `/dev/dri` exists, that you're on Raspberry Pi OS **Lite**, and that `dtoverlay=vc4-kms-v3d` is set, or uncomment `privileged: true` in `docker-compose.yml` and run `docker compose up -d`. |
| **`no such file or directory` for `/dev/dri`** | You're not on a Pi with KMS enabled (or you're on a PC or Chromebook). Start only the updater: `docker compose up -d updater`. |
| **Can't open the network share** | Run `systemctl status smbd` and `testparm -s`. Check the user name is `cinema` and the password is the one set with `smbpasswd` (not necessarily the login password). Try the IP address instead of the name. On Windows, an old saved login can interfere: Credential Manager, remove the entry for the Pi. |
| **Can open the share but can't save or delete files** | The folder's owner isn't `cinema` (if you ran `docker compose up` as `sudo`, or before the folders existed, Docker may have created them as root). Fix with `sudo chown -R cinema:cinema ~/empire-kiosk/cinema-kiosk/slides ~/empire-kiosk/cinema-kiosk/static ~/empire-kiosk/cinema-kiosk/logs ~/empire-kiosk/cinema-kiosk/video`, then `docker compose up -d`. |
| **Updater says `Permission denied` writing to `/data`, `/logs` or `/video`** | The same thing: those folders aren't writable by the user in `docker-compose.yml` (`1000:1000`). Run the `chown` above and check `id cinema`. |

## 15. Maintenance, backups and removal

- **Keep the OS up to date** every month or so: `sudo apt update && sudo apt full-upgrade -y`, then
  `sudo reboot` when convenient. Docker itself is updated this way too.
- **Refresh the container base images** now and then, to pick up security fixes:

  ```bash
  cd ~/empire-kiosk/cinema-kiosk
  docker compose build --pull
  docker compose up -d
  docker image prune -f
  ```

- **Power**: if you can, switch the Pi off cleanly (`sudo shutdown now`) rather than pulling the plug, and
  keep it on a surge-protected supply. SD cards occasionally corrupt after power cuts. Keep a spare,
  pre-made card.
- **Back up what's yours**: `.env`, the `static` folder and the `fonts` folder. Everything else is
  rebuilt from the code and the website. (Easiest is to copy them off through the network shares, or with
  `scp -r cinema@foyer-kiosk.local:~/empire-kiosk/cinema-kiosk/static .` from your computer.)
- **Disk space**: the slides take a few MB per film and the updater keeps only the current and previous
  set. The `slides/archive` folder grows slowly and is never deleted automatically; see
  [USAGE.md](USAGE.md#rendered-slides-and-the-archive). Check space with `df -h /`, and
  `docker system df` and `docker image prune -f` for Docker.

**Starting over.** To delete the generated slides and make a fresh set (your settings and `static` images
are kept):

```bash
cd ~/empire-kiosk/cinema-kiosk
docker compose down
rm -rf slides/gen-* slides/current slides/archive
docker compose up -d --build        # the first update runs straight away
```

**Removing the kiosk completely:**

```bash
cd ~/empire-kiosk/cinema-kiosk && docker compose down --rmi all
cd ~ && rm -rf empire-kiosk
```

Then remove the two shares from `/etc/samba/smb.conf` (the `[static]` and `[slides]` blocks) and run
`sudo systemctl restart smbd`.
