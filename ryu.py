# ryu.py - SDN CDN Controller Application
# This Ryu application acts as a load balancer for the CDN simulation.
# It dynamically redirects HTTP requests for the central server to the nearest
# or least congested edge server.

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser
from ryu.lib.packet import packet, ethernet, ipv4, arp, tcp
from ryu.lib.mac import haddr_to_bin

class CDNLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(CDNLoadBalancer, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.ip_to_mac = {}

        # Static mapping of client subnets to their nearest edge server IPs.
        self.client_subnet_to_edge_map = {
            '10.0.1.0/24': '10.0.1.1', # h4 -> h2
            '10.0.2.0/24': '10.0.2.1'  # h5 -> h3
        }
        self.edge_servers = {
            '10.0.1.1': {'connections': 0, 'datapath': None},
            '10.0.2.1': {'connections': 0, 'datapath': None}
        }
        self.central_server_ip = '10.0.0.1' # IP of the central server (h1)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        # Default rule: send unmatched packets to controller
        match = ofp_parser.OFPMatch()
        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        # ARP flooding rule
        match_arp = ofp_parser.OFPMatch(eth_type=ofp.OFP_ETH_TYPE_ARP)
        actions_arp = [ofp_parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        self.add_flow(datapath, 100, match_arp, actions_arp)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        inst = [ofp_parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = ofp_parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    def find_least_congested_server(self, client_ip):
        """
        Determines the best edge server to redirect to based on proximity and congestion.
        """
        best_server_ip = None
        min_connections = float('inf')

        # First, try to find the "closest" server based on subnet mapping
        client_subnet = '.'.join(client_ip.split('.')[:-1]) + '.0/24'
        if client_subnet in self.client_subnet_to_edge_map:
            closest_server_ip = self.client_subnet_to_edge_map[client_subnet]
            return closest_server_ip

        # If the closest server is not available or mapped, fall back to least congested
        for ip, data in self.edge_servers.items():
            if data['connections'] < min_connections:
                min_connections = data['connections']
                best_server_ip = ip
        
        self.logger.info(f"Client {client_ip} redirected to least congested server {best_server_ip}")
        return best_server_ip

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        
        src_mac = eth.src
        dpid = datapath.id
        
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        _arp = pkt.get_protocol(arp.arp)
        if _arp:
            self.ip_to_mac[_arp.src_ip] = _arp.src_mac
            self.logger.info(f"Learned ARP: IP={_arp.src_ip}, MAC={_arp.src_mac} on dpid={dpid}")
            return

        _ipv4 = pkt.get_protocol(ipv4.ipv4)
        _tcp = pkt.get_protocol(tcp.tcp)
        
        if _ipv4 and _tcp and _tcp.dst_port == 80:
            src_ip = _ipv4.src
            dst_ip = _ipv4.dst

            target_server_ip = dst_ip
            
            if dst_ip == self.central_server_ip:
                target_server_ip = self.find_least_congested_server(src_ip)
                if target_server_ip in self.edge_servers:
                    self.edge_servers[target_server_ip]['connections'] += 1
                    self.logger.info(f"Redirecting HTTP request from {src_ip} (original dst: {dst_ip}) to {target_server_ip}. Active connections: {self.edge_servers[target_server_ip]['connections']}")

            target_server_mac = self.ip_to_mac.get(target_server_ip)
            out_port = self.mac_to_port[dpid].get(target_server_mac) if target_server_mac else ofp.OFPP_FLOOD

            if target_server_mac and out_port != ofp.OFPP_FLOOD:
                actions = [
                    ofp_parser.OFPActionSetField(ipv4_dst=target_server_ip),
                    ofp_parser.OFPActionSetField(eth_dst=target_server_mac),
                    ofp_parser.OFPActionOutput(out_port)
                ]
                match = ofp_parser.OFPMatch(
                    in_port=in_port,
                    eth_type=ofp.OFP_ETH_TYPE_IP,
                    ip_proto=6,
                    ipv4_src=src_ip,
                    ipv4_dst=dst_ip,
                    tcp_dst=_tcp.dst_port
                )
                self.add_flow(datapath, 10, match, actions, idle_timeout=300, hard_timeout=600)
            
            actions = [ofp_parser.OFPActionOutput(out_port)]
            out = ofp_parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data)
            datapath.send_msg(out)
            return

        dst_mac = eth.dst
        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [ofp_parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = ofp_parser.OFPMatch(in_port=in_port, eth_dst=dst_mac)
            self.add_flow(datapath, 1, match, actions)

        out = ofp_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data)
        datapath.send_msg(out)

