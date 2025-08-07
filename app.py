# app.py
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel
import subprocess
import time
import os

class MultiRegionTopo(Topo):
    def build(self):
        # Add switches
        central_switch = self.addSwitch('s1')
        edge_switch1 = self.addSwitch('s2')
        edge_switch2 = self.addSwitch('s3')
        
        # Add a router host
        router = self.addHost('r1')

        # Add hosts with their default gateways pointing to the router
        central_server = self.addHost('h1', ip='10.0.0.1/24', defaultRoute='via 10.0.0.254')
        edge_server1 = self.addHost('h2', ip='10.0.1.1/24', defaultRoute='via 10.0.1.254')
        edge_server2 = self.addHost('h3', ip='10.0.2.1/24', defaultRoute='via 10.0.2.254')
        client1 = self.addHost('h4', ip='10.0.1.100/24', defaultRoute='via 10.0.1.254')
        client2 = self.addHost('h5', ip='10.0.2.100/24', defaultRoute='via 10.0.2.254')

        # Links with bandwidths
        self.addLink(central_server, central_switch, cls=TCLink, bw=100)
        self.addLink(edge_server1, edge_switch1, cls=TCLink, bw=100)
        self.addLink(edge_server2, edge_switch2, cls=TCLink, bw=100)
        self.addLink(client1, edge_switch1, cls=TCLink, bw=100)
        self.addLink(client2, edge_switch2, cls=TCLink, bw=100)

        # Bottlenecks
        self.addLink(edge_switch1, central_switch, cls=TCLink, bw=10)
        self.addLink(edge_switch2, central_switch, cls=TCLink, bw=20)
        
        # Connect the router to the switches
        self.addLink(router, central_switch)
        self.addLink(router, edge_switch1)
        self.addLink(router, edge_switch2)

def run():
    setLogLevel('info')
    
    # Automated cleanup before starting
    print("Attempting to clean up Mininet environment...")
    subprocess.run(['sudo', 'mn', '-c'], check=False)
    
    # Start the Ryu controller in the background
    print("Starting Ryu controller...")
    ryu_app_path = os.path.join(os.path.dirname(__file__), 'ryu.py')
    ryu_proc = subprocess.Popen(['ryu-manager', ryu_app_path], preexec_fn=os.setsid)
    time.sleep(5)  # Give Ryu time to start

    net = None
    try:
        topo = MultiRegionTopo()
        net = Mininet(
            topo=topo,
            switch=OVSSwitch,
            link=TCLink,
            controller=RemoteController
        )

        net.start()
        
        # Configure the router interfaces and enable IP forwarding
        r1 = net.get('r1')
        r1.cmd('ifconfig r1-eth0 10.0.0.254 netmask 255.255.255.0')
        r1.cmd('ifconfig r1-eth1 10.0.1.254 netmask 255.255.255.0')
        r1.cmd('ifconfig r1-eth2 10.0.2.254 netmask 255.255.255.0')
        r1.cmd('sysctl -w net.ipv4.ip_forward=1')

        print("\nConfiguring host routes for inter-subnet communication...")
        h1 = net.get('h1')
        h1.cmd('route add -net 10.0.1.0/24 gw 10.0.0.254')
        h1.cmd('route add -net 10.0.2.0/24 gw 10.0.0.254')
        h2 = net.get('h2')
        h2.cmd('route add -net 10.0.0.0/24 gw 10.0.1.254')
        h2.cmd('route add -net 10.0.2.0/24 gw 10.0.1.254')
        h3 = net.get('h3')
        h3.cmd('route add -net 10.0.0.0/24 gw 10.0.2.254')
        h3.cmd('route add -net 10.0.1.0/24 gw 10.0.2.254')
        h4 = net.get('h4')
        h4.cmd('route add -net 10.0.0.0/24 gw 10.0.1.254')
        h4.cmd('route add -net 10.0.2.0/24 gw 10.0.1.254')
        h5 = net.get('h5')
        h5.cmd('route add -net 10.0.0.0/24 gw 10.0.2.254')
        h5.cmd('route add -net 10.0.1.0/24 gw 10.0.2.254')

        print("\nHost Connections: ")
        for host in net.hosts:
            print(f"{host.name} -> {host.IP()}")
        
        # Start a simple Python web server on h1 to act as the backend
        print("\nStarting a simple Python web server on h1...")
        h1 = net.get('h1')
        h1.cmd('mkdir -p /var/www/html')
        h1.cmd(f'echo "<html><body><h1>Hello from h1 (Central Server)</h1></body></html>" > /var/www/html/bbb.mpd')
        h1.cmd('python3 -m http.server 80 -d /var/www/html &')
        print(f"  - Web server started on h1 at {h1.IP()}")

        # Configure and start Nginx on h2 and h3
        print("\nConfiguring and starting Nginx on h2 and h3...")
        h2 = net.get('h2')
        h3 = net.get('h3')

        nginx_conf = """
server {
    listen 80;
    root /var/www/html;
    index bbb.mpd;
}
"""


        for host in [h2, h3]:
            print(f"  - Installing Nginx on {host.name}...")
            host.cmd('apt-get update && apt-get install -y nginx')
            
            host.cmd('mkdir -p /etc/nginx/sites-available')
            host.cmd('mkdir -p /var/www/html')
            
            print(f"  - Creating Nginx configuration for {host.name}...")
            host.cmd(f'echo "{nginx_conf}" > /etc/nginx/sites-available/default')

            print(f"  - Enabling Nginx site on {host.name}...")
            host.cmd('ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default')
            
            host.cmd(f'echo "<html><body><h1>Hello from {host.name} (Edge Server)</h1></body></html>" > /var/www/html/bbb.mpd')
            
            print(f"  - Starting Nginx on {host.name}...")
            host.cmd('nginx &')
        
        time.sleep(5)
        
        print("\nTesting Connectivity (pingAll)...")
        net.pingAll()

        print("\nTesting file transfer over port 80...")
        client1 = net.get('h4')
        client2 = net.get('h5')
        
        print(f"  - Client {client1.name} (h4) fetching from its local Edge Server (h2)...")
        result2 = client1.cmd('wget -O - h2/bbb.mpd')
        print(f"    Result: {result2.strip()}")

        print(f"  - Client {client2.name} (h5) fetching from its local Edge Server (h3)...")
        result3 = client2.cmd('wget -O - h3/bbb.mpd')
        print(f"    Result: {result3.strip()}")
        
        print("\nStarting Mininet CLI...")
        CLI(net)
    
    finally:
        if net:
            net.stop()
        if 'ryu_proc' in locals() and ryu_proc:
            print("Stopping Ryu controller...")
            os.killpg(os.getpgid(ryu_proc.pid), 9) # Kill the entire process group
            ryu_proc.wait()

if __name__ == '__main__':
    run()
