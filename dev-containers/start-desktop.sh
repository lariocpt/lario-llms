#!/bin/bash
set -e

echo "Starting Dev Container graphical desktop environment..."

# 1. Clean up stale VNC and X11 locks from any abrupt shutdowns
rm -rf /tmp/.X11-unix/X1 /tmp/.X10-unix/X1 /tmp/.X1-lock

# 2. Pre-create the VNC configuration directory for 'dev' user
mkdir -p /home/dev/.vnc

# 3. Create the xstartup script which runs when TigerVNC starts
cat << 'EOF' > /home/dev/.vnc/xstartup
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
[ -x /etc/vnc/xstartup ] && exec /etc/vnc/xstartup
[ -r $HOME/.Xresources ] && xrdb $HOME/.Xresources
xsetroot -solid grey
vncconfig -iconic &
exec startxfce4
EOF
chmod +x /home/dev/.vnc/xstartup

# 4. Set up beautiful XFCE4 configurations (Dark theme & custom branded wallpaper)
mkdir -p /home/dev/.config/xfce4/xfconf/xfce-perchannel-xml/

# Create the desktop config pointing to the wallpaper at /usr/share/backgrounds/wallpaper.svg
cat << 'EOF' > /home/dev/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitor0" type="empty">
        <property name="workspace0" type="empty">
          <property name="color-style" type="int" value="0"/>
          <property name="image-style" type="int" value="5"/>
          <property name="last-image" type="string" value="/usr/share/backgrounds/wallpaper.svg"/>
        </property>
      </property>
      <property name="monitorVNC-0" type="empty">
        <property name="workspace0" type="empty">
          <property name="color-style" type="int" value="0"/>
          <property name="image-style" type="int" value="5"/>
          <property name="last-image" type="string" value="/usr/share/backgrounds/wallpaper.svg"/>
        </property>
      </property>
    </property>
  </property>
</channel>
EOF

# Set default XFCE themes (Adwaita-dark theme looks gorgeous, standard icons)
cat << 'EOF' > /home/dev/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Net" type="empty">
    <property name="ThemeName" type="string" value="Adwaita-dark"/>
    <property name="IconThemeName" type="string" value="Adwaita"/>
  </property>
</channel>
EOF

# Ensure all configurations in the home directory are owned by 'dev'
chown -R dev:dev /home/dev/.vnc /home/dev/.config

# 5. Start the TigerVNC server on display :1 (port 5901) without password restriction (safe on local network)
vncserver :1 -geometry 1280x800 -depth 24 -SecurityTypes None

# 6. Set up the noVNC index symlink to bypass the files listing page
if [ -d /usr/share/novnc ]; then
    ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html || true
fi

# 7. Start the websockify VNC-to-WebSockets proxy on port 8080
websockify --web=/usr/share/novnc 8080 localhost:5901 &

echo "Desktop Environment is active!"
echo "Access this container's GUI at: http://localhost:<port>"

# 8. Create a dummy log if not generated yet, and tail the log so the container stays running
touch /home/dev/.vnc/dev-pop:1.log /home/dev/.vnc/dev-ubuntu:1.log /home/dev/.vnc/dev-mint:1.log
chown dev:dev /home/dev/.vnc/*.log

# Tail all VNC logs so any errors are captured in Docker container logs
tail -f /home/dev/.vnc/*.log
