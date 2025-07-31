import struct

input_file = 'C:\\Users\\fadhil.musyaffa\\Downloads\\itch-ordermdf.bin'

field_schema = [
    ('char', 1),
    ('int', 4),
    ('int', 4),
    ('char', 1),
    ('str', 32),
    ('str', 64),
    ('str', 12),
    ('str', 32),
    ('char', 1),
    ('str', 3),
    ('short', 2),
    ('short', 2),
    ('int', 4),
    ('long', 8),
    ('char', 1),
    ('int', 4),
    ('long', 8),
    ('int', 4),
    ('short', 2),
    ('char', 1),
    ('int', 4),
    ('int', 4),
    ('short', 2),
    ('int', 4),
    ('long', 8),
    ('long', 8),
    ('int', 4),
    ('long', 8),
    ('long', 8),
    ('short', 2),
    ('long', 8),
    ('long', 8),
    ('int', 4),
    ('char', 1),
    ('char', 1),
    ('str', 32),
    ('long', 8),
    ('long', 8),
    ('short', 2),
    ('str', 100),
    ('int', 4),
    ('int', 4),
    ('long', 8),
    ('int', 4),
    ('str', 40),
    ('char', 1)
]

def unpack_message(msg_bytes):
    offset = 0
    values = []



    for typ, size in field_schema:
        chunk = msg_bytes[offset:offset + size]
        if typ == 'char':
            val = chunk.decode('ascii').strip()
        elif typ == 'str':
            val = chunk.decode('ascii').rstrip()
        elif typ == 'short':
            val = struct.unpack('<H', chunk)[0]
        elif typ == 'int':
            val = struct.unpack('<I', chunk)[0]
        elif typ == 'long':
            val = struct.unpack('<Q', chunk)[0]
        values.append(val)
        offset += size

    return values



with open(input_file, 'rb') as f:
    while True:
        header = f.read(8)
        if len(header) < 8:
            break  # EOF or corrupted

        row_no, msg_len = struct.unpack('<II', header)
        msg_bytes = f.read(msg_len)
        values = unpack_message(msg_bytes)
        print(f"{row_no}: {values}")


    print(f"{row_no}: {msg_len} bytes → {msg_bytes}")
