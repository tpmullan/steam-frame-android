#!/system/bin/sh
# The Frame kernel has no legacy iptables tables (filter/mangle/raw), so
# Android 13 netd fails networkAddInterface and never installs its
# per-network routing rules or default route. Route everything through the
# main table instead, with pasta's gateway as the default route. Runs for the
# life of the container: Android's IpClient removes main-table routes when it
# (re)configures eth0, so put the default route back whenever it goes missing.
GW=172.20.0.1
while true; do
	if ip rule | grep -q '^32000:' && ip -4 addr show eth0 | grep -q 'inet '; then
		ip rule | grep -q '^31000:' || ip rule add from all lookup main prio 31000
		ip route | grep -q '^default ' || ip route replace default via $GW dev eth0
	fi
	sleep 2
done
