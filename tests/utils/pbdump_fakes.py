import struct

def pack_varint(n):
    res = b''
    while n > 127:
        res += struct.pack('B', (n & 0x7F) | 0x80)
        n >>= 7
    res += struct.pack('B', n)
    return res

def pack_msg(field, wire, data):
    k = (field << 3) | wire
    res = pack_varint(k)
    if wire == 2:
        res += pack_varint(len(data)) + data
    elif wire == 0:
        res += pack_varint(data)
    elif wire == 5:
        res += data
    return res
