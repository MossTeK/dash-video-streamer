# ryu.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser
from ryu.lib.packet import packet, ethernet, ipv4, arp, tcp # Added tcp for HTTP handling
from ryu.lib.mac import haddr_to_bin

class CDNLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(CDNLoadBalancer, self).__init__(*args, **kwargs)
        self.mac_to_port = {} 
        self.ip_to_mac = {}   

        self.client_to_edge_server_map = {
            '10.0.1.100': '10.0.1.1',
            '10.0.2.100': '10.0.2.1'  
        }
        self.central_server_ip = '10.0.0.1' # IP of the central server (h1)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        match = ofp_parser.OFPMatch()
        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                               ofp.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        match_arp = ofp_parser.OFPMatch(eth_type=ofp.OFP_ETH_TYPE_ARP)
        actions_arp = [ofp_parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        self.add_flow(datapath, 100, match_arp, actions_arp)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        """
        Installs a flow entry into the OpenFlow switch.
        """
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        inst = [ofp_parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = ofp_parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout # Flow will be removed after this time
        )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
        Handles incoming packets that are sent to the controller.
        This is where the intelligent routing logic resides.
        """
        msg = ev.msg
        datapath = msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        dst_mac = eth.dst
        src_mac = eth.src
        dpid = datapath.id # Datapath ID (switch ID)
        
        # Learn the source MAC address and its incoming port on this switch
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        # --- ARP Packet Handling ---
        _arp = pkt.get_protocol(arp.arp)
        if _arp:
            # Learn IP-to-MAC mapping from ARP requests/replies
            self.ip_to_mac[_arp.src_ip] = _arp.src_mac
            self.logger.info(f"Learned ARP: IP={_arp.src_ip}, MAC={_arp.src_mac} on dpid={dpid}")

            # Determine output port for ARP: if destination MAC is known, send directly, else flood
            if dst_mac in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst_mac]
            else:
                out_port = ofp.OFPP_FLOOD # Flood if destination MAC is unknown
            
            actions = [ofp_parser.OFPActionOutput(out_port)]
            
            # Send the ARP packet out
            out = ofp_parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data)
            datapath.send_msg(out)
            return # ARP packet handled, no further processing for this packet

        _ipv4 = pkt.get_protocol(ipv4.ipv4)
        _tcp = pkt.get_protocol(tcp.tcp)

        if _ipv4 and _tcp and _tcp.dst_port == 80:
            src_ip = _ipv4.src
            dst_ip = _ipv4.dst # Original destination IP
            
            self.logger.info(f"HTTP request from {src_ip} to {dst_ip} on dpid={dpid}")

            target_server_ip = dst_ip # Default target is the original destination
            
            if dst_ip == self.central_server_ip:
                if src_ip in self.client_to_edge_server_map:
                    preferred_edge_server_ip = self.client_to_edge_server_map[src_ip]
                    target_server_ip = preferred_edge_server_ip
                    self.logger.info(f"Redirecting HTTP request from {src_ip} (original dst: {dst_ip}) to {target_server_ip}")
            
            target_server_mac = self.ip_to_mac.get(target_server_ip)
            
            if not target_server_mac:
                self.logger.warning(f"MAC for target server {target_server_ip} not learned yet. Flooding.")
                out_port = ofp.OFPP_FLOOD
                actions = [ofp_parser.OFPActionOutput(out_port)]
                data_to_send = msg.data # Send original packet data
            else:
                out_port = self.mac_to_port[dpid].get(target_server_mac)
                if not out_port:
                    self.logger.warning(f"Port for target server MAC {target_server_mac} on dpid={dpid} not learned yet. Flooding.")
                    out_port = ofp.OFPP_FLOOD
                    actions = [ofp_parser.OFPActionOutput(out_port)]
                    data_to_send = msg.data # Send original packet data
                else:
                    # If redirection occurred (target_server_ip is different from original dst_ip)
                    if target_server_ip != dst_ip:
                        # Create new Ethernet header with the target server's MAC
                        new_eth = ethernet.ethernet(dst=target_server_mac, src=src_mac, ethertype=eth.ethertype)
                        
                        new_ipv4 = ipv4.ipv4(
                            version=_ipv4.version, header_length=_ipv4.header_length,
                            tos=_ipv4.tos, total_length=_ipv4.total_length,
                            identification=_ipv4.identification, flags=_ipv4.flags,
                            offset=_ipv4.offset, ttl=_ipv4.ttl, proto=_ipv4.proto,
                            csum=_ipv4.csum, src=_ipv4.src, dst=target_server_ip # Modified destination IP
                        )
                        
                        new_pkt = packet.Packet()
                        new_pkt.add_protocol(new_eth)
                        new_pkt.add_protocol(new_ipv4)
                        
                        for p in pkt.protocols[2:]:
                            new_pkt.add_protocol(p)
                        
                        data_to_send = new_pkt.serialize() # Serialize the modified packet
                        self.logger.info(f"Packet from {src_ip} rewritten: original_dst={dst_ip}, new_dst={target_server_ip}")
                    else:

                        data_to_send = msg.data 

                    actions = [
                        ofp_parser.OFPActionSetField(ipv4_dst=target_server_ip),
                        ofp_parser.OFPActionSetField(eth_dst=target_server_mac),
                        ofp_parser.OFPActionOutput(out_port)
                    ]
                    

                    match = ofp_parser.OFPMatch(
                        in_port=in_port,
                        eth_type=ofp.OFP_ETH_TYPE_IP,
                        ip_proto=6, # TCP protocol
                        ipv4_src=src_ip,
                        ipv4_dst=dst_ip, # Match original destination IP
                        tcp_dst=_tcp.dst_port
                    )
                    self.add_flow(datapath, 10, match, actions, idle_timeout=300, hard_timeout=600) # Flow timeout after 5/10 minutes

            # Send the packet out (either original or modified)
            out = ofp_parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data_to_send)
            datapath.send_msg(out)
            return # HTTP packet handled, no further processing

        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
        else:
            out_port = ofp.OFPP_FLOOD # Flood if destination MAC is unknown

        actions = [ofp_parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = ofp_parser.OFPMatch(in_port=in_port, eth_dst=dst_mac)
            self.add_flow(datapath, 1, match, actions) # Lower priority (1) than HTTP rules

        # Send the packet out
        out = ofp_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data)
        datapath.send_msg(out)
