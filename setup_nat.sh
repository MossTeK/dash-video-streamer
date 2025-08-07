#!/bin/bash

# This script sets up NAT (Network Address Translation) on the router 'r1'.
# It enables IP forwarding and configures iptables rules for masquerading.

echo "Configuring NAT on $(hostname)..."

# 1. Enable IP Forwarding (already done in app.py, but good to ensure)
sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1
echo "  - IP forwarding enabled."

# 2. Clear existing iptables rules (optional, but good for clean setup)
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X
echo "  - Cleared existing iptables rules."

# 3. Set up NAT (Masquerading) for traffic from client subnets to the central subnet
# Traffic originating from 10.0.1.0/24 or 10.0.2.0/24 going out through r1-eth0 (to 10.0.0.0/24)
# will have its source IP translated to r1-eth0's IP (10.0.0.254).
# This allows the central server to send replies back to r1, which then de-NATs them.

# Rule for traffic from 10.0.1.0/24 (Edge Region 1) to central subnet
iptables -t nat -A POSTROUTING -s 10.0.1.0/24 -o r1-eth0 -j MASQUERADE
echo "  - NAT rule added for 10.0.1.0/24 to r1-eth0."

# Rule for traffic from 10.0.2.0/24 (Edge Region 2) to central subnet
iptables -t nat -A POSTROUTING -s 10.0.2.0/24 -o r1-eth0 -j MASQUERADE
echo "  - NAT rule added for 10.0.2.0/24 to r1-eth0."

# Optional: Add a general forwarding rule to allow packets to pass through
# This is usually handled by default if IP forwarding is on, but explicitly adding can help.
# iptables -A FORWARD -i r1-eth1 -o r1-eth0 -j ACCEPT
# iptables -A FORWARD -i r1-eth2 -o r1-eth0 -j ACCEPT
# iptables -A FORWARD -i r1-eth0 -o r1-eth1 -j ACCEPT
# iptables -A FORWARD -i r1-eth0 -o r1-eth2 -j ACCEPT

echo "NAT setup complete on $(hostname)."

