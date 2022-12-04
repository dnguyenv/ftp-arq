"""
Authors Stephen Bennett & Duy Ngyuen
Dec 2, 2022
"""

import socket, pickle, random, os, argparse

p = argparse.ArgumentParser()
p.add_argument("SERVER_PORT", type=int)
p.add_argument("FILE_NAME")
p.add_argument("PACKET_LOSS_PROB", type=float)
args = p.parse_args()

SERVER_PORT = args.SERVER_PORT
FILE_NAME = args.FILE_NAME
PACKET_LOSS_PROB =  args.PACKET_LOSS_PROB

TYPE_DATA = "0101010101010101"
TYPE_ACK = "1010101010101010"
TYPE_EOF = "1111111111111111"
DATA_PAD = "0000000000000000"

ACK_PORT = 7737
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
HOST_NAME = '0.0.0.0' # all interfaces
ACK_HOST_NAME = ''
server_socket.bind((HOST_NAME, SERVER_PORT))
last_received_packet = -1

def compute_checksum_server(chunk, checksum):
    l = len(chunk)
    chunk = str(chunk)
    # print(f'chunk is : {chunk}')
    b = 0
    #Take 2 bytes of from the chunk data 
    while b < l:
        byte1 = ord(chunk[b])
        shifted_byte1 = byte1 << 8
        if b + 1 == l: # last one
            byte2 = 0xffff
        else:
            byte2 = ord(chunk[b+1])
        merged_bytes = shifted_byte1 + byte2
        checksum_add = checksum + merged_bytes
        carryover = checksum_add >> 16
        main_part = checksum_add & 0xffff
        checksum = main_part + carryover
        b = b + 2
    checksum_complement = checksum ^ 0xffff
    return checksum_complement

#Send the ack back to the sender
def send_ack(ack_number):
    ack_packet = pickle.dumps([ack_number, DATA_PAD, TYPE_ACK])
    ack_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ack_socket.sendto(ack_packet,(ACK_HOST_NAME, ACK_PORT))
    ack_socket.close()

def is_good_checksum(chunk,checksum):
    return compute_checksum_server(chunk,checksum)==0

def check_if_packet_drop(PACKET_LOSS_PROB,packet_sn):
    return random.random() < PACKET_LOSS_PROB

# Simply save data to a file
def write_data_to_file(packet_data):
    with open(FILE_NAME, 'ab') as file:
        file.write(packet_data)

def entrance():
    global last_received_packet, ACK_HOST_NAME
    DONE = False # completion flag
    while not DONE:
        # Receive data from the sender
        received_data1, addr = server_socket.recvfrom(ACK_PORT)
        ACK_HOST_NAME = addr[0]        # Pick up the sender's hostname to send the ACK packets back
        #print(f'ACK_HOST_NAME: {ACK_HOST_NAME}')
        received_data = pickle.loads(received_data1)
        packet_sn, packet_checksum, packet_type, packet_data = received_data[0], received_data[1], received_data[2], received_data[3]
        #Check if the packet is last packet
        if packet_type == TYPE_EOF:
            DONE = True
            server_socket.close()
        elif packet_type == TYPE_DATA:
            #Check if the packet needs to be dropped due to probability
            drop_packet = check_if_packet_drop(PACKET_LOSS_PROB,packet_sn)

            if drop_packet:
                print (f'Packet lost, sequence number = {packet_sn}')
            else:
                # Check checksum
                if is_good_checksum(packet_data, packet_checksum):
                    if packet_sn==last_received_packet + 1:
                        send_ack(packet_sn+1)
                        last_received_packet = last_received_packet + 1
                        #Write the data to the file
                        write_data_to_file(packet_data)
                    else:
                        #Else send the ACK of the expected packet
                        send_ack(last_received_packet + 1)
                else:
                    print (f'Packet {packet_sn} has been dropped due to invalid checksum')

if __name__ == "__main__":
    entrance()

