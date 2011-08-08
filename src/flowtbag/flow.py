#!/usr/bin/python

'''
   Copyright 2011 Daniel Arndt

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

   Contributors:

   @author: Daniel Arndt <danielarndt@gmail.com>
'''
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import *
# Retrieve the default logger, should have been initialized by the Flowtbag.
log = logging.getLogger()

#---------------------------------------------------------------------- Settings
FLOW_TIMEOUT = 600 # Flow timeout in seconds 
IDLE_THRESHOLD = 1.0
#----------------------------------------------------------------- End: Settings
#------------------------------------------------------------- Non-Configurables
TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_PSH = 0x08
TCP_ACK = 0x10
TCP_URG = 0x20
#-------------------------------------------------------- End: Non-Configurables


def stddev(sqsum, sum, count):
    return math.sqrt((sqsum - (sum ** 2 / count)) / (count - 1))

def tcp_set(find, flags):
    '''
    Checks if a flag is set or not.
    
    Args:
        find - The flag to find
        flags - The string encoded set of flags
    Returns:
        True - if the /find/ flag is set
        False - otherwise
    '''
    log.debug("find: %s flags: %s" % (type(find), flags))
    return ((find & flags) == find)

#==============================================================================#
# TCP connection states. These define the finite state machine used for        #
# verifying TCP flow validity.                                                 #
#==============================================================================#
class STATE_TCP(object):
    ''' 
    Superclass for a TCP connection state machine.  
    
    Defines the behavior of a state within a generalized finite state machine.
    Currently, the rules perfectly resemble those used by NetMate
    '''
    #TODO: Update the state machine to include more robust checks. Current 
    # implementation imitates NetMate state machine. 
    def update(self, flags, dir, _pdir):
        '''
        Updates the TCP state machine.
        
        First the RST and FIN flags are checked. If either of these are set, the
        connection state is set to either TCP_CLOSED or TCP_FIN respectively.
        Next, the function attempts to find a transition in the map called /tr/.
        If no transition is found, then the function returns itself. 
        
        '''
        if tcp_set(flags, TCP_RST):
            return STATE_TCP_CLOSED()
        if tcp_set(flags, TCP_FIN) and dir == _pdir:
            return STATE_TCP_FIN()
        # Add all states satisfied by the function in the map /tr/ given /flags/
        next_state = [ s for f, s in self.tr if f(flags, dir, _pdir)]
        try:
            return eval(next_state[0])()
        except:
            return self # Default to no transition

    def __str__(self):
        return self.__class__.__name__

class STATE_TCP_START(STATE_TCP):
    tr = [(lambda flags, dir, pdir: 
           tcp_set(flags, TCP_SYN) and dir == pdir, 
           "STATE_TCP_SYN")]

class STATE_TCP_SYN(STATE_TCP):
    tr = [(lambda flags, dir, pdir: 
           tcp_set(flags, TCP_SYN) and
           tcp_set(flags, TCP_ACK) and dir != pdir, 
           "STATE_TCP_SYNACK")]

class STATE_TCP_SYNACK(STATE_TCP):
    tr = [(lambda flags, dir, pdir: 
           tcp_set(flags, TCP_ACK) and dir == pdir, 
           "STATE_TCP_ESTABLISHED")]

class STATE_TCP_ESTABLISHED(STATE_TCP):
    tr = []

class STATE_TCP_FIN(STATE_TCP):
    tr = [(lambda flags, dir, pdir: 
           tcp_set(flags, TCP_ACK) and dir != pdir, 
           "STATE_TCP_CLOSED")]

class STATE_TCP_CLOSED(STATE_TCP):
    tr = []
#-------------------------------------------------------- End: TCP state machine

#==============================================================================#
# Begin code for Flow class                                                    #
#==============================================================================#
class Flow:
    '''
    Represents one flow to be stored in a flowtbag.
    
    An object of this class represents one flow in a flowtbag. The Flow object 
    contains several statistics about the flow as well as stores the first 
    packet of the flow for reference.
    
    Variable naming conventions:
        Prefix - desc
        _  - Instance variable used for storing information about the flow which 
             is important for calculations or identification purposes but is not
             part of the output.
            
        a_ - Instance variables representing an attribute to be exported as a
             flow attribute (feature).
             
        c_ - Counter variables, used for counting totals and other statistics to
             help in calculating attributes. 
    
    '''
    def __init__(self, pkt, id):
        '''
        Constructor. Initialize all values.
        '''
        # Set initial values
        self._id = id
        self._first_packet = pkt
        self._valid = False
        self._pdir = "f"
        self._first = pkt['time']
        self._flast = pkt['time']
        self._blast = 0
        #------------------------------------ Basic flow identification criteria
        self.a_srcip = pkt['srcip']
        self.a_srcport = pkt['srcport']
        self.a_dstip = pkt['dstip']
        self.a_dstport = pkt['dstport']
        self.a_proto = pkt['proto']
        self.dscp = pkt['dscp'] # Bit shift twice to the right to get DSCP
                                     # TODO: verify this is working correctly.
        #--------------------------------------------------------------------- #
        self.a_total_fpackets = 1
        self.a_total_fvolume = pkt['len']
        self.a_total_bpackets = 0
        self.a_total_bvolume = 0
        self.a_min_fpktl = pkt['len']
        self.a_mean_fpktl = 0
        self.a_max_fpktl = pkt['len']
        self.a_std_fpktl = 0
        self.c_fpktl_sqsum = (pkt['len'] ** 2)
        self.a_min_bpktl = 0
        self.a_mean_bpktl = 0
        self.a_max_bpktl = 0
        self.a_std_bpktl = 0
        self.c_bpktl_sqsum = 0
        self.a_min_fiat = 0
        self.a_mean_fiat = 0
        self.a_max_fiat = 0
        self.a_std_fiat = 0
        self.c_fiat_sum = 0
        self.c_fiat_sqsum = 0
        self.c_fiat_count = 0
        self.a_min_biat = 0
        self.a_mean_biat = 0
        self.a_max_biat = 0
        self.a_std_biat = 0
        self.c_biat_sum = 0
        self.c_biat_sqsum = 0
        self.c_biat_count = 0
        self.a_duration = 0
        self.a_min_active = 0
        self.a_mean_active = 0
        self.a_max_active = 0
        self.a_std_active = 0
        self.c_active_start = self._first
        self.c_active_time = 0
        self.c_active_sqsum = 0
        self.c_active_count = 0
        self.a_min_idle = 0
        self.a_mean_idle = 0
        self.a_max_idle = 0
        self.a_std_idle = 0
        self.c_idle_time = 0
        self.c_idle_sqsum = 0
        self.c_idle_count = 0
        self.a_sflow_fpackets = 0
        self.a_sflow_fbytes = 0
        self.a_sflow_bpackets = 0
        self.a_sflow_bbytes = 0
        if pkt['proto'] == 6:
            # TCP specific
            # Create state machines for the client and server 
            self._cstate = STATE_TCP_START() # Client state
            self._sstate = STATE_TCP_START() # Server state
            # Set TCP flag stats
            if (tcp_set(pkt['flags'], TCP_PSH)):
                self.a_fpsh_cnt = 1
            else:
                self.a_fpsh_cnt = 0
            if (tcp_set(pkt['flags'], TCP_URG)):
                self.a_furg_cnt = 1
            else:
                self.a_furg_cnt = 0
        else:
            # We still need to set these for UDP so when we access them we do
            # not get an error.
            self.a_fpsh_cnt = 0
            self.a_furg_cnt = 0
        # Backward counts will always start as zero
        self.a_bpsh_cnt = 0
        self.a_burg_cnt = 0
        self.a_total_fhlen = pkt['iphlen'] + pkt['prhlen']
        self.a_total_bhlen = 0
        self.update_status(pkt)

    def __repr__(self):
        return "[%d:(%s,%d,%s,%d,%d)]" % \
            (self._id, self.a_srcip, self.a_srcport, self.a_dstip,
             self.a_dstport, self.a_proto)

    def __str__(self):
        '''
        Exports the stats collected.
        '''
        # Count the last active time
        diff = self.get_last_time() - self.c_active_start
        if diff > self.a_max_active:
            self.a_max_active = diff
        if diff < self.a_min_active or self.a_min_active == 0:
            self.a_min_active = diff
        self.c_active_time += diff
        self.c_active_sqsum += (diff ** 2)
        self.c_active_count += 1

        assert(self.a_total_fpackets > 0)
        self.a_mean_fpktl = self.a_total_fvolume / self.a_total_fpackets
        # Standard deviation of packets in the forward direction
        if self.a_total_fpackets > 1:
            self.a_std_fpktl = stddev(self.c_fpktl_sqsum,
                                      self.a_total_fvolume,
                                      self.a_total_fpackets)
        else:
            self.a_std_fpktl = 0
        # Mean packet length of packets in the packward direction
        if self.a_total_bpackets > 0:
            self.a_mean_bpktl = self.a_total_bvolume / self.a_total_bpackets
        else:
            self.a_mean_bpktl = -1
        # Standard deviation of packets in the backward direction
        if self.a_total_bpackets > 1:
            self.a_std_bpktl = stddev(self.c_bpktl_sqsum,
                                      self.a_total_bvolume,
                                      self.a_total_bpackets)
        else:
            self.a_std_bpktl = 0
        # Mean forward inter-arrival time
        # TODO: Check if we actually need c_fiat_count ?
        if self.c_fiat_count > 0:
            self.a_mean_fiat = self.c_fiat_sum / self.c_fiat_count
        else:
            self.a_mean_fiat = 0
        # Standard deviation of forward inter-arrival times
        if self.c_fiat_count > 1:
            self.a_std_fiat = stddev(self.c_fiat_sqsum,
                                     self.c_fiat_sum,
                                     self.c_fiat_count)
        else:
            self.a_std_fiat = 0
        # Mean backward inter-arrival time
        if self.c_biat_count > 0:
            self.a_mean_biat = self.c_biat_sum / self.c_biat_count
        else:
            self.a_mean_biat = 0
        # Standard deviation of backward inter-arrival times
        if self.c_biat_count > 1:
            self.a_std_biat = stddev(self.c_biat_sqsum,
                                     self.c_biat_sum,
                                     self.c_biat_count)
        else:
            self.a_std_biat = 0
        # Mean active time of the sub-flows
        if self.c_active_count > 0:
            self.a_mean_active = self.c_active_time / self.c_active_count
        else:
            # There should be packets in each direction if we're exporting 
            log.debug("ERR: This shouldn't happen")
            raise Exception
        # Standard deviation of active times of sub-flows
        if self.c_active_count > 1:
            self.a_std_active = stddev(self.c_active_sqsum,
                                       self.c_active_time,
                                       self.c_active_count)
        else:
            self.a_std_active = 0
        # Mean of idle times between sub-flows
        if self.c_idle_count > 0:
            self.a_mean_idle = self.c_idle_time / self.c_idle_count
        else:
            self.a_mean_idle = 0
        # Standard deviation of idle times between sub-flows
        if self.c_idle_count > 1:
            self.a_std_idle = stddev(self.c_idle_sqsum,
                                     self.c_idle_time,
                                     self.c_idle_count)
        else:
            self.a_std_idle = 0
        # More sub-flow calculations
        if self.c_active_count > 0:
            self.a_sflow_fpackets = self.a_total_fpackets / self.c_active_count
            self.a_sflow_fbytes = self.a_total_fvolume / self.c_active_count
            self.a_sflow_bpackets = self.a_total_bpackets / self.c_active_count
            self.a_sflow_bbytes = self.a_total_bvolume / self.c_active_count
        self.a_duration = self.get_last_time() - self._first

        assert (self.a_duration > 0)

        export = [
                  self.a_srcip,
                  self.a_srcport,
                  self.a_dstip,
                  self.a_dstport,
                  self.a_proto,
                  self.a_total_fpackets,
                  self.a_total_fvolume,
                  self.a_total_bpackets,
                  self.a_total_bvolume,
                  self.a_min_fpktl,
                  int(self.a_mean_fpktl),
                  self.a_max_fpktl,
                  int(self.a_std_fpktl),
                  self.a_min_bpktl,
                  int(self.a_mean_bpktl),
                  int(self.a_max_bpktl),
                  int(self.a_std_bpktl),
                  int(1000000 * self.a_min_fiat),
                  int(1000000 * self.a_mean_fiat),
                  int(1000000 * self.a_max_fiat),
                  int(1000000 * self.a_std_fiat),
                  int(1000000 * self.a_min_biat),
                  int(1000000 * self.a_mean_biat),
                  int(1000000 * self.a_max_biat),
                  int(1000000 * self.a_std_biat),
                  int(1000000 * self.a_duration),
                  int(1000000 * self.a_min_active),
                  int(1000000 * self.a_mean_active),
                  int(1000000 * self.a_max_active),
                  int(1000000 * self.a_std_active),
                  int(1000000 * self.a_min_idle),
                  int(1000000 * self.a_mean_idle),
                  int(1000000 * self.a_max_idle),
                  int(1000000 * self.a_std_idle),
                  self.a_sflow_fpackets,
                  self.a_sflow_fbytes,
                  self.a_sflow_bpackets,
                  self.a_sflow_bbytes,
                  self.a_fpsh_cnt,
                  self.a_bpsh_cnt,
                  self.a_furg_cnt,
                  self.a_burg_cnt,
                  self.a_total_fhlen,
                  self.a_total_bhlen
                  ]
        return ','.join(map(str, export))

    def update_tcp_state(self, pkt):
        '''
        Updates the TCP connection state
        
        Checks to see if a valid TCP connection has been made. The function uses
        a finite state machine implemented through the TCP_STATE class and its 
        sub-classes.
        
        Args:
            pkt - the packet to be analyzed to update the TCP connection state
                  for the flow.
        '''
        # Update client state
        self._cstate = self._cstate.update(pkt['flags'], "f", self._pdir)
        # Update server state
        self._sstate = self._sstate.update(pkt['flags'], "b", self._pdir)

    def update_status(self, pkt):
        '''
        Updates the status of a flow, checking if the flow is a valid flow.
        
        In the case of UDP, this is a simple check upon whether at least one
        packet has been sent in each direction.
        
        In the case of TCP, the validity check is a little more complex. A valid
        TCP flow requires that a TCP connection is established in the usual way.
        Furthermore, the TCP flow is terminated when a TCP connection is closed,
        or upon a timeout defined by FLOW_TIMEOUT.
        
        Args:
            pkt - the packet to be analyzed for updating the status of the flow.
        '''
        if pkt['proto'] == 17:
            # UDP
            # Skip if already labelled valid
            if self._valid: return
            # If packet length is over 8 (size of a UDP header), then we have
            # at least one byte of data
            if pkt['len'] > 8:
                self.has_data = True
            if self.has_data and self.a_total_bpackets > 0:
                self._valid = True
        elif pkt['proto'] == 6:
            # TCP
            if isinstance(self._cstate, STATE_TCP_ESTABLISHED):
                hlen = pkt['iphlen'] + pkt['prlen']
                if pkt['len'] > hlen:
                    #TODO: Why would we need a hasdata variable such as in NM?
                    self._valid = True
            if not self._valid:
                #Check validity
                pass
            self.update_tcp_state(pkt)
        else:
            raise NotImplementedError

    def get_last_time(self):
        '''
        Returns the time stamp of the most recent packet in the flow, be it the
        last packet in the forward direction, or the last packet in the backward
        direction.
        
        Reimplementation of the NetMate flowstats method 
        getLast(struct flowData_t). 
        
        Returns:
            The timestamp of the last packet.
        '''
        if (self._blast == 0):
            return self._flast
        elif (self._flast == 0):
            return self._blast
        else:
            return self._flast if (self._flast > self._blast) else self._blast

    def add(self, pkt):
        '''
        Add a packet to the current flow.
        
        This function adds the packet, provided as an argument, to the flow.
        
        Args:
            pkt: The packet to be added
        Returns:
            0 - the packet is successfully added to the flow
            1 - the flow is complete with this packet (ie. TCP connect closed)
            2 - the packet is not part of this flow. (ie. flow timeout exceeded) 
        '''
        # TODO: Robust check of whether or not the packet is part of the flow.
        now = pkt['time']
        last = self.get_last_time()
        diff = now - last
        if diff > FLOW_TIMEOUT:
            return 2

        #Gather some statistics
        len = pkt['len']
        hlen = pkt['iphlen'] + pkt['prhlen']
        assert (now >= self._first)
        # Ignore re-ordered packets
        if (now < last):
            log.info("Flow: ignoring reordered packet. %d < %d" %
                      (now, last))
            return 0
            #raise NotImplementedError
        # Update the global variable _pdir which holds the direction of the
        # packet currently in question.  
        if (pkt['srcip'] == self._first_packet['srcip']):
            self._pdir = "f"
        else:
            self._pdir = "b"
        # Set attributes.
        if diff > IDLE_THRESHOLD:
            # The flow has been idle previous to this packet, so calc idle time 
            # stats
            if diff > self.a_max_idle:
                self.a_max_idle = diff
            if diff < self.a_min_idle or self.a_min_idle == 0:
                self.a_min_idle = diff
            self.c_idle_time += diff
            self.c_idle_sqsum += (diff ** 2)
            self.c_idle_count += 1
            # Active time stats - calculated by looking at the previous packet
            # time and the packet time for when the last idle time ended.
            diff = last - self.c_active_start
            if diff > self.a_max_active:
                self.a_max_active = diff
            if diff < self.a_min_active or self.a_min_active == 0:
                self.a_min_active = diff
            self.c_active_time += diff
            self.c_active_sqsum += (diff ** 2)
            self.c_active_count += 1
            self._flast = 0
            self._blast = 0
            self.c_active_start = now
        # Set bi-directional attributes.
        if self._pdir == "f":
            # Packet is travelling in the forward direction
            # Calculate some statistics
            # Packet length
            if len < self.a_min_fpktl or self.a_min_fpktl == 0:
                self.a_min_fpktl = len
            if len > self.a_max_fpktl:
                self.a_max_fpktl = len
            self.a_total_fvolume += len # Doubles up as c_fpktl_sum from NM
            self.c_fpktl_sqsum += (len ** 2)
            self.a_total_fpackets += 1
            self.a_total_fhlen += hlen
            # Interarrival time
            if self._flast > 0:
                diff = now - self._flast
                if diff < self.a_min_fiat or self.a_min_fiat == 0:
                    self.a_min_fiat = diff
                if diff > self.a_max_fiat:
                    self.a_max_fiat = diff
                self.c_fiat_sum += diff
                self.c_fiat_sqsum += (diff ** 2)
                self.c_fiat_count += 1
            if pkt['proto'] == 6:
                # Packet is using TCP protocol
                if (tcp_set(pkt['flags'], TCP_PSH)):
                    self.a_fpsh_cnt += 1
                if (tcp_set(pkt['flags'], TCP_URG)):
                    self.a_furg_cnt += 1
            # Update the last forward packet time stamp
            self._flast = now
        else:
            # Packet is travelling in the backward direction, check if dscp is
            # set in this direction
            if self._blast == 0 and self.dscp == 0:
                # Check only first packet in backward dir, and make sure it has
                # not been set already.
                self.dscp = pkt['dscp']
            # Calculate some statistics
            # Packet length
            if len < self.a_min_bpktl or self.a_min_bpktl == 0:
                self.a_min_bpktl = len
            if len > self.a_max_bpktl:
                self.a_max_bpktl = len
            self.a_total_bvolume += len # Doubles up as c_bpktl_sum from NM
            self.c_bpktl_sqsum += (len ** 2)
            self.a_total_bpackets += 1
            self.a_total_bhlen += hlen
            # Inter-arrival time
            if self._blast > 0:
                diff = now - self._blast
                if diff < self.a_min_biat or self.a_min_biat == 0:
                    self.a_min_biat = diff
                if diff > self.a_max_biat:
                    self.a_max_biat = diff
                self.c_biat_sum += diff
                self.c_biat_sqsum += (diff ** 2)
                self.c_biat_count += 1
            if pkt['proto'] == 6:
                # Packet is using TCP protocol
                if (tcp_set(pkt['flags'], TCP_PSH)):
                    self.a_bpsh_cnt += 1
                if (tcp_set(pkt['flags'], TCP_URG)):
                    self.burg_cnt += 1
            # Update the last backward packet time stamp
            self._blast = now

        # Update the status (validity, TCP connection state) of the flow.
        self.update_status(pkt)            

        if (pkt['proto'] == 6 and
            isinstance(self._cstate, STATE_TCP_CLOSED) and
            isinstance(self._sstate, STATE_TCP_CLOSED)):
            return 1
        else:
            return 0
    
    def checkidle(self, time):
        return True if time - self.get_last_time() > FLOW_TIMEOUT else False
        
    def export(self):
        if self._valid:
            print self
#--------------------------------------------------------------------- End: Flow