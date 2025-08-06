# ryu.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser
from ryu.lib.packet import packet, ethernet, ipv4, arp
from ryu.lib.mac import haddr_to_bin

class SimpleL2Switch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleL2Switch, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        # Install a default low-priority rule to send unmatched packets to the controller
        match = ofp_parser.OFPMatch()
        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                              ofp.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        # Install a high-priority rule for ARP to flood
        match_arp = ofp_parser.OFPMatch(eth_type=ofp.OFP_ETH_TYPE_ARP)
        actions_arp = [ofp_parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        self.add_flow(datapath, 100, match_arp, actions_arp)

        # Install a high-priority rule for IPv4 TCP traffic on port 80
        match_http = ofp_parser.OFPMatch(
            eth_type=ofp.OFP_ETH_TYPE_IP,
            ip_proto=6,  # TCP protocol number
            tcp_dst=80
        )
        actions_http = [ofp_parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        self.add_flow(datapath, 100, match_http, actions_http)

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

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        
        self.mac_to_port.setdefault(dpid, {})

        # Learning switch logic: learn the source port
        self.mac_to_port[dpid][src] = in_port
        
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [ofp_parser.OFPActionOutput(out_port)]

        # If a new path is found, add a new flow entry to the switch
        if out_port != ofp.OFPP_FLOOD:
            match = ofp_parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)
            
        out = ofp_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data)
        datapath.send_msg(out)
