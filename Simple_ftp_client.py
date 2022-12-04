"""
Authors Stephen Bennett & Duy Ngyuen
Dec 2, 2022
"""

import socket, sys, collections, pickle, signal, time, argparse
import threading
from multiprocessing import Lock
from collections import namedtuple

RTT = 0.1 

#ACK_HOST = '0.0.0.0'
ACK_HOST = ''
ACK_PORT = 7737 

TYPE_DATA = "0101010101010101"
TYPE_ACK = "1010101010101010"
TYPE_EOF = "1111111111111111"

client_buffer = collections.OrderedDict() # buffer to keep packets to be sent
sliding_window = set() # sliding window
max_seq_number=0 # SN of the last packet
last_ack_packet = -1  # ACK received from server
last_send_packet = -1  # thje last packet SN sent to the server

# dummy namedtuples which are complete packets (+ header and data, used for for packet transations
ack_packet = namedtuple('ack_packet', 'sequence_no padding type')
data_packet = namedtuple('data_packet', 'sequence_no checksum type data')

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
thread_lock = Lock()
sending_completed = False

# Execution time (for reporting)
start_time=0
end_time=0

p = argparse.ArgumentParser()
p.add_argument("SEND_HOST")
p.add_argument("SEND_PORT", type=int)
p.add_argument("FILE_NAME")
p.add_argument("WINDOW_SIZE", type=int)
p.add_argument("MSS_SIZE", type = int)

args = p.parse_args()

SEND_HOST = args.SEND_HOST
SEND_PORT = args.SEND_PORT
FILE_NAME = args.FILE_NAME
N =  args.WINDOW_SIZE
MSS =  args.MSS_SIZE


def send_packet_to_host(packet, host, port, socket, sequence_no):    
    client_socket.sendto(packet,(host,port)) 

# Handle the packets sending, as described in the project requirement
def rdt_send(file_content, client_socket, host, port):
    global last_send_packet,last_ack_packet,sliding_window,client_buffer,start_time    
    start_time=time.time()

    while len(sliding_window)<min(len(client_buffer),N):        
        if last_ack_packet==-1:            
            send_packet_to_host(client_buffer[last_send_packet+1], host, port, client_socket, last_send_packet+1)
            signal.alarm(0)
            signal.setitimer(signal.ITIMER_REAL, RTT)
            last_send_packet = last_send_packet + 1
            sliding_window.add(last_send_packet)
            x = 0
            while x < 100000: # dumb trick 
                x = x + 1

def compute_checksum_client(chunk):
    checksum = 0
    l = len(chunk)
    chunk = str(chunk)
    byte=0
    while byte < l:        
        byte1 = ord(chunk[byte])
        shifted_byte1 = byte1 << 8
        if byte+1==l:
            byte2=0xffff
        else:
            byte2=ord(chunk[byte+1])
        # Merge the bytes to make 16 bits
        merged_bytes = shifted_byte1 + byte2
        # Add to the 16 bit chekcsum
        checksum_add = checksum + merged_bytes
        # Compute the carryover
        carryover = checksum_add >> 16
        # main part of the new checksum
        main_part = checksum_add & 0xffff
        #Add the carryover
        checksum = main_part + carryover
        byte = byte+2
    #Pick the 1's complement of the computed checksum to return
    checksum_complement = checksum ^ 0xffff
    return checksum_complement

# Function to monitor time outs
def timeout_threading(thread, frame):
    global last_ack_packet
    if last_ack_packet == last_send_packet - len(sliding_window):
         print (f'Timeout, sequence number = {last_ack_packet + 1}')         
         thread_lock.acquire()
         #Resend packets in the sliding window from the timeout packet
         for i in range(last_ack_packet + 1,last_ack_packet + 1 + len(sliding_window), 1):
            signal.alarm(0) # notify
            signal.setitimer(signal.ITIMER_REAL, RTT)
            send_packet_to_host(client_buffer[i], SEND_HOST, SEND_PORT, client_socket, i) # send again
         thread_lock.release()

#Monitoring the incoming ACKs and send remaining packets
def ack_processing():
    global last_ack_packet,last_send_packet,client_buffer,sliding_window,client_socket,SEND_PORT,SEND_HOST,sending_completed,end_time,start_time,total_time # dumb usage of global vars
    # Listening to the incoming ACKs
    ack_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ack_socket.bind((ACK_HOST, ACK_PORT))

    while True:        
        response = pickle.loads(ack_socket.recv(ACK_PORT))
        # If incoming packet is an ACK
        if response[2] == TYPE_ACK:
            current_ack_sn = response[0]-1
            if last_ack_packet >= -1:

                thread_lock.acquire()
                """If this is the last ACK, then send the eof packet to the receiver, release the thread control, 
                and adjust the end time"""
                if current_ack_sn == max_seq_number:
                    eof_packet = pickle.dumps(["0", "0", TYPE_EOF, "0"])
                    client_socket.sendto(eof_packet, (SEND_HOST, SEND_PORT))
                    thread_lock.release()
                    sending_completed = True
                    end_time = time.time()
                    total_time = end_time - start_time # manually calculate the time
                    break                 
                elif current_ack_sn > last_ack_packet:
                    # If new ACK
                    while last_ack_packet<current_ack_sn:
                        signal.alarm(0)
                        signal.setitimer(signal.ITIMER_REAL, RTT)
                        last_ack_packet = last_ack_packet + 1
                        sliding_window.remove(last_ack_packet)
                        client_buffer.pop(last_ack_packet)
                        while len(sliding_window) < min(len(client_buffer),N):
                            if last_send_packet < max_seq_number:
                                send_packet_to_host(client_buffer[last_send_packet + 1],SEND_HOST,SEND_PORT,client_socket,last_send_packet + 1)
                                sliding_window.add(last_send_packet + 1)
                                last_send_packet=last_send_packet + 1                    
                    thread_lock.release()
                else:
                    thread_lock.release()

def entrance():
    global client_buffer ,max_seq_number,client_socket,N,SEND_PORT,SEND_HOST,MSS # make it simply dumb, as long as it does the job
   
    """Read the data from the input file, split it into chunks based on MSS size, 
    keep the chunkks in client_buffer using on the sequence number, and calculate the last sequence number"""
    sequence_number = 0
    try:
        with open(FILE_NAME, 'rb') as file:
            while True:
                chunk = file.read(MSS)  
                if chunk:
                    max_seq_number = sequence_number
                    chunk_checksum = compute_checksum_client(chunk)
                    client_buffer[sequence_number] = pickle.dumps([sequence_number,chunk_checksum,TYPE_DATA,chunk])
                    sequence_number = sequence_number + 1
                else:
                    break
    except:
        sys.exit("Can't open the file. Please check again.")

    signal.signal(signal.SIGALRM, timeout_threading)    
    ack_thread = threading.Thread(target=ack_processing)
    ack_thread.start() 	
    #Initial packet sending
    rdt_send(client_buffer, client_socket, SEND_HOST, SEND_PORT)
    #Monitor if the sending is complete
    while True:
        if sending_completed:
            break
    print(f'Total time: {total_time}')    
    ack_thread.join()
    #close the socket
    client_socket.close()

if __name__ == "__main__":
    entrance()

