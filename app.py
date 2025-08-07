# app.py - Mininet Testbed & Experiment Automation
# This script sets up the Mininet topology, configures servers, and
# automates experiments to test the SDN controller's performance.

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info
import subprocess
import time
import os
import datetime

# --- Topology Design (Goal 1) ---
class MultiRegionTopo(Topo):
    """
    Defines a multi-region network topology for a CDN.
    Includes bottleneck links to simulate bandwidth constraints.
    """
    def build(self):
        info('*** Adding switches\n')
        central_switch = self.addSwitch('s1')
        edge_switch1 = self.addSwitch('s2')
        edge_switch2 = self.addSwitch('s3')
        
        info('*** Adding router and hosts\n')
        router = self.addHost('r1')
        
        central_server = self.addHost('h1', ip='10.0.0.1/24', defaultRoute='via 10.0.0.254')
        edge_server1 = self.addHost('h2', ip='10.0.1.1/24', defaultRoute='via 10.0.1.254')
        edge_server2 = self.addHost('h3', ip='10.0.2.1/24', defaultRoute='via 10.0.2.254')
        client1 = self.addHost('h4', ip='10.0.1.100/24', defaultRoute='via 10.0.1.254')
        client2 = self.addHost('h5', ip='10.0.2.100/24', defaultRoute='via 10.0.2.254')

        info('*** Adding links with bandwidths\n')
        self.addLink(central_server, central_switch, cls=TCLink, bw=100)
        self.addLink(edge_server1, edge_switch1, cls=TCLink, bw=100)
        self.addLink(edge_server2, edge_switch2, cls=TCLink, bw=100)
        self.addLink(client1, edge_switch1, cls=TCLink, bw=100)
        self.addLink(client2, edge_switch2, cls=TCLink, bw=100)

        # Bottleneck links to simulate variable network conditions
        self.addLink(edge_switch1, central_switch, cls=TCLink, bw=10, delay='20ms')
        self.addLink(edge_switch2, central_switch, cls=TCLink, bw=20, delay='10ms')
        
        # Router connections
        self.addLink(router, central_switch)
        self.addLink(router, edge_switch1)
        self.addLink(router, edge_switch2)

def generate_video_files(host):
    """
    Creates placeholder DASH video files and an MPD file on a given host.
    This simulates the video segmentation process.
    """
    video_dir = '/var/www/html/videos'
    host.cmd(f'mkdir -p {video_dir}')
    
    # Placeholder MPD file content
    mpd_content = f"""
    <MPD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT5M0S" minBufferTime="PT2S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
      <Period>
        <AdaptationSet id="0" contentType="video" startWithSAP="1" segmentAlignment="true" subsegmentAlignment="true">
          <Representation id="1" bandwidth="2000000" codecs="avc1.4d401e" mimeType="video/mp4">
            <BaseURL>videos/video_2Mbps.mp4</BaseURL>
          </Representation>
        </AdaptationSet>
      </Period>
    </MPD>
    """
    host.cmd(f'echo \'{mpd_content}\' > /var/www/html/bbb.mpd')
    
    # Placeholder video file
    host.cmd(f'head -c 5M /dev/urandom > {video_dir}/video_2Mbps.mp4')
    
    info(f'--- Video files created on {host.name}\n')

def configure_and_start_servers(net):
    """
    Configures and starts Nginx on edge servers and a simple server on h1.
    """
    info('*** Configuring and starting servers...\n')
    
    h1 = net.get('h1')
    info(f'  - Starting simple Python web server on h1 at {h1.IP()}\n')
    h1.cmd('mkdir -p /var/www/html')
    generate_video_files(h1)
    h1.cmd('python3 -m http.server 80 -d /var/www/html &')

    for host in [net.get('h2'), net.get('h3')]:
        info(f'  - Installing and starting Nginx on {host.name}\n')
        host.cmd('apt-get update && apt-get install -y nginx')
        host.cmd('mkdir -p /var/www/html')
        host.cmd('mkdir -p /etc/nginx/sites-available')
        generate_video_files(host)
        
        nginx_conf = f"""
server {{
    listen 80;
    root /var/www/html;
    index bbb.mpd;
}}
"""
        host.cmd(f'echo "{nginx_conf}" > /etc/nginx/sites-available/default')
        host.cmd('ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default')
        host.cmd('nginx')
        
    time.sleep(5)
    info('*** Servers configured and running.\n')

# --- Experiment Automation (Goals 3 & 4) ---
def run_experiments(net, log_file):
    """
    Runs automated experiments to measure performance and logs the results.
    """
    info('*** Starting automated experiments...\n')
    h4 = net.get('h4')
    h5 = net.get('h5')
    
    # Scenario 1: Accessing the central server directly (without SDN redirection)
    info('*** SCENARIO 1: Central Server Access (bypassing SDN)\n')
    log_file.write(f'SCENARIO 1: Central Server Access (bypassing SDN) - {datetime.datetime.now()}\n')
    
    # Measure latency
    central_server_ip = net.get('h1').IP()
    ping_output = h4.cmd(f'ping -c 5 {central_server_ip}')
    log_file.write('Latency from h4 to h1:\n')
    log_file.write(ping_output + '\n')
    
    # Measure bandwidth and download time
    wget_output = h4.cmd(f'wget -O - {central_server_ip}/bbb.mpd 2>&1 | grep "saved"')
    log_file.write('File download from h1 (h4 client):\n')
    log_file.write(wget_output + '\n\n')
    
    # Scenario 2: Accessing the edge server via SDN redirection
    info('*** SCENARIO 2: Edge Server Access (with SDN redirection)\n')
    log_file.write(f'SCENARIO 2: Edge Server Access (with SDN redirection) - {datetime.datetime.now()}\n')

    edge_server_ip = net.get('h2').IP()
    ping_output = h4.cmd(f'ping -c 5 {edge_server_ip}')
    log_file.write('Latency from h4 to h2:\n')
    log_file.write(ping_output + '\n')
    
    wget_output = h4.cmd(f'wget -O - {central_server_ip}/bbb.mpd 2>&1 | grep "saved"')
    log_file.write('File download from h1 (h4 client, redirected by SDN):\n')
    log_file.write(wget_output + '\n\n')
    
    info('*** Automated experiments completed. Check results.log for data.\n')
    log_file.close()


def run():
    setLogLevel('info')
    
    info('*** Attempting to clean up Mininet environment...\n')
    subprocess.run(['sudo', 'mn', '-c'], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # --- Deploy SDN Controller (Goal 2) ---
    info('*** Starting Ryu controller...\n')
    ryu_app_path = os.path.join(os.path.dirname(__file__), 'ryu.py')
    ryu_proc = subprocess.Popen(['ryu-manager', ryu_app_path], preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(5)

    net = None
    try:
        topo = MultiRegionTopo()
        net = Mininet(
            topo=topo,
            switch=OVSSwitch,
            link=TCLink,
            controller=RemoteController,
            autoSetMacs=True, # Added to simplify network setup
            autoStaticArp=True # Added to simplify network setup
        )

        # Add NAT to connect Mininet network to the outside world
        net.addNAT().configDefault()
        
        net.start()
        
        r1 = net.get('r1')
        r1.cmd('ifconfig r1-eth0 10.0.0.254 netmask 255.255.255.0')
        r1.cmd('ifconfig r1-eth1 10.0.1.254 netmask 255.255.255.0')
        r1.cmd('ifconfig r1-eth2 10.0.2.254 netmask 255.255.255.0')
        r1.cmd('sysctl -w net.ipv4.ip_forward=1')

        info('*** Configuring host routes...\n')
        h1 = net.get('h1')
        h1.cmd('route add -net 10.0.1.0/24 gw 10.0.0.254')
        h1.cmd('route add -net 10.0.2.0/24 gw 10.0.0.254')
        for host in [net.get('h2'), net.get('h4')]:
            host.cmd('route add -net 10.0.0.0/24 gw 10.0.1.254')
            host.cmd('route add -net 10.0.2.0/24 gw 10.0.1.254')
        for host in [net.get('h3'), net.get('h5')]:
            host.cmd('route add -net 10.0.0.0/24 gw 10.0.2.254')
            host.cmd('route add -net 10.0.1.0/24 gw 10.0.2.254')

        configure_and_start_servers(net)

        # Open the log file for experiments
        with open('results.log', 'a') as log_file:
            run_experiments(net, log_file)

        info('*** Running Mininet CLI for further manual testing.\n')
        CLI(net)
    
    finally:
        if net:
            net.stop()
        if 'ryu_proc' in locals() and ryu_proc:
            info('*** Stopping Ryu controller...\n')
            os.killpg(os.getpgid(ryu_proc.pid), 9)
            ryu_proc.wait()

if __name__ == '__main__':
    run()

