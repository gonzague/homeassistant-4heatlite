# Proxy Modes

Local TCP write support depends on the controller. Direct writes have been verified with the [Jolly Mec profile](JOLLYMEC.md), which can operate without this proxy. For controllers that require cloud polling for writes, the proxy provides a local command delivery path. The integration includes an embedded HTTP proxy that intercepts the module's cloud traffic and injects local commands, using Home Assistant's native `HomeAssistantView` pattern. No extra processes or ports on the HA side.

## Architecture

```
                    ┌──────────────┐
                    │  4HEAT App   │
                    └──────┬───────┘
                           │ HTTPS (wifi4heat.azurewebsites.net)
                    ┌──────▼───────┐
                    │  Azure Cloud  │◄── mirror (cloud_keepalive only)
                    └──────────────┘
                                      ┌──────────────────────┐
┌─────────┐  RS485    ┌──────────────┐│  HA (port 8123)      │
│  Stove  │◄─────────►│ 4HEAT Module ├┤  HomeAssistantView   │
│         │  Tiemme   │              ││  proxy endpoints     │
└─────────┘           └──────────────┘└──────────────────────┘
                         HTTP ▲              │
                         DNAT:80             │ HTTPS mirror
                              └──────────────┘ (register + store)
```

The module connects to what it thinks is `wifi4heat-linux.azurewebsites.net:80` (Azure cloud). A DNS override on the router resolves this hostname to the router's LAN IP, and a firewall DNAT rule redirects the traffic to Home Assistant.

## Modes

### `direct` (default)

- Module traffic goes to Azure directly — no DNS override needed.
- HA polls the module via TCP on port 80 for sensor data (read-only).
- Commands from HA are sent to the module via the cloud command queue.
- The mobile app works normally.
- **Limitation**: HA depends on the module's TCP server being reachable on the LAN.

### `cloud_keepalive`

- Module traffic is intercepted and handled locally by HA (requires DNS override + DNAT).
- Commands from HA are queued and delivered to the module when it polls.
- `/register` and `/store` requests are **mirrored to Azure** via HTTPS, keeping the device online in Azure's records.
- The mobile app works — Azure reports `IsOnline: true` because it receives the mirrored store keepalives.
- **Best of both worlds**: local command control + mobile app compatibility.

#### What gets mirrored

| Module Request | Local | Azure Mirror |
|----------------|-------|-------------|
| `POST /api/devices/register` | Handle + respond | Yes — keeps Azure device registration current |
| `POST /api/devices/store` | Parse sensor data | Yes — keeps `IsOnline: true` |
| `GET /api/devices/commands` | Drain local queue | No — HA controls commands exclusively |
| `GET /api/Devices/timeAlign` | Local clock sync | No |
| `POST /api/devices/cron` | Store schedule | No |

The mirror uses the HTTPS endpoint (`wifi4heat.azurewebsites.net`), which is **not affected** by the DNS override (that only applies to the HTTP hostname `wifi4heat-linux.azurewebsites.net`). Mirror requests are fire-and-forget — failures are logged but do not affect local operation.

### `local_only`

- Module traffic is intercepted and handled locally by HA.
- Commands from HA are queued and delivered to the module when it polls.
- **No data is forwarded to Azure** — the device appears offline in Azure.
- The mobile app will show "No device found" / "Dispositivo inalcanzable" because Azure reports `IsOnline: false`.

## Network Setup (OpenWrt)

Required for `local_only` and `cloud_keepalive` modes. Not needed for `direct` mode.

The module connects to `wifi4heat-linux.azurewebsites.net` on port 80 (HTTP). To redirect this traffic to HA, you need a DNS override and a firewall DNAT rule on your router. The DNAT target depends on whether HA listens on HTTP or HTTPS.

### Step 1: DNS Override

Resolve the cloud hostname to your router's LAN IP:

```bash
uci add_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/<ROUTER_IP>'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

### Step 2: Firewall DNAT

Choose the scenario that matches your HA setup:

#### Scenario A — HA listens on HTTP (default)

If `http:` in `configuration.yaml` has no `ssl_certificate` configured and no SSL proxy add-on is active, HA accepts plain HTTP on port 8123. DNAT directly to HA:

```bash
uci add firewall redirect
uci set firewall.@redirect[-1].name='4heat-proxy'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_ip='<MODULE_IP>'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='<HA_IP>'
uci set firewall.@redirect[-1].dest_port='8123'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'
uci commit firewall
/etc/init.d/firewall restart
```

#### Scenario B — HA listens on HTTPS

If HA uses TLS (e.g., via `ssl_certificate`, the Let's Encrypt add-on, or the NGINX SSL proxy add-on), the module cannot connect directly — it speaks plain HTTP only. Use [stunnel](https://www.stunnel.org/) on the router as a TLS wrapper:

```bash
# Install stunnel
apk add stunnel   # OpenWrt 25.x+
# opkg install stunnel  # older OpenWrt

# Configure stunnel as a TLS client
cat > /etc/stunnel/4heat.conf << 'EOF'
pid = /var/run/stunnel-4heat.pid
[4heat-proxy]
client = yes
accept = 8180
connect = <HA_IP>:8123
verifyChain = no
EOF

# Enable and start
/etc/init.d/stunnel enable
/etc/init.d/stunnel start
```

stunnel accepts plain HTTP on port 8180 and wraps it in TLS before forwarding to HA:8123. Then DNAT to stunnel instead of HA directly:

```bash
uci add firewall redirect
uci set firewall.@redirect[-1].name='4heat-proxy'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_ip='<MODULE_IP>'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='<ROUTER_IP>'
uci set firewall.@redirect[-1].dest_port='8180'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'
uci commit firewall
/etc/init.d/firewall restart
```

Replace `<MODULE_IP>` with your module's IP, `<ROUTER_IP>` with your router's LAN IP, and `<HA_IP>` with your Home Assistant server's IP.

> **Note**: LAN-to-LAN DNAT (hairpin NAT) may require an additional masquerade rule on some OpenWrt configurations.

### Multiple Modules

To proxy multiple stoves, add one DNAT rule per module (different `src_ip`, same destination). The proxy routes requests to the correct stove entry using the device ID from the module's requests.

### How to Check if HA Uses HTTP or HTTPS

```bash
# From a machine on the same LAN:
curl -v http://<HA_IP>:8123/ 2>&1 | head -15
```

- If you get an HTML response: HA uses **HTTP** (Scenario A).
- If you get `Empty reply from server` or a TLS error: HA uses **HTTPS** (Scenario B).

## Reverting to Cloud

To restore full cloud connectivity, switch to `direct` mode in the integration options and remove the DNS override and firewall redirect:

```bash
uci del_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/<ROUTER_IP>'
uci commit dhcp
/etc/init.d/dnsmasq restart

# Remove the firewall redirect (find its index with: uci show firewall | grep 4heat)
uci delete firewall.@redirect[N]
uci commit firewall
/etc/init.d/firewall restart
```

The module will reconnect to Azure within ~60 seconds.
