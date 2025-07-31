import csv
import struct
import json

input_filename = 'C:\\Users\\fadhil.musyaffa\\Downloads\\itch-ordermdf.csv'
output_filename = 'C:\\Users\\fadhil.musyaffa\\Downloads\\itch-ordermdf.bin'

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

def extract_json_values(json_str):
    fixed = json_str.replace('""', '"').strip('" \n')
    parsed = json.loads(fixed)
    return list(parsed.values())

def pack_field(val, typ, size):
    try:


        if typ == 'char':
            return struct.pack('c', str(val).encode('ascii')[0:1])
        elif typ == 'str':
            b = str(val).encode('ascii', errors='ignore')
            return b[:size].ljust(size, b' ')
        elif typ in ('short', 'int', 'long'):
            val_clean = str(val).strip()
            if val_clean == "":
                val_clean = "0"
            num = int(val_clean)
            if typ == 'short':
                return struct.pack('<H', num)
            elif typ == 'int':
                return struct.pack('<I', num)
            elif typ == 'long':
                return struct.pack('<Q', num)
    except Exception as e:
        print(f"Error packing field {val} as {typ} ({size} bytes): {e}")
        return b'\x00' * size

with open(input_filename, mode='r', encoding='US_ASCII', newline='') as infile, open(output_filename, mode='wb') as outfile:
    reader = csv.reader(infile, delimiter=';')
    headers = next(reader)  # Skip header

    for i, row in enumerate(reader, start=1):
        if len(row) < 3:
            continue

        raw_json = row[2]

        try:
            values = extract_json_values(raw_json)
        except Exception as e:
            print(f"Row {i} failed to parse JSON: {e}")
            continue

        if len(values) != len(field_schema):
            print(f"Row {i} skipped: expected {len(field_schema)} fields, got {len(values)}")
            continue

        # Pack fields
        packed_fields = []
        print(f"\nRow {i} field breakdown:")
        for idx, (val, (typ, size)) in enumerate(zip(values, field_schema)):
            packed = pack_field(val, typ, size)
            packed_fields.append(packed)
            print(f"  [{idx}] {typ:<5} → {repr(val):<40} → {len(packed)} bytes")

        binary_msg = b''.join(packed_fields)
        total_len = len(binary_msg)

        # Write: 4-byte row index + 4-byte length + binary content
        outfile.write(struct.pack('<I', i))
        outfile.write(struct.pack('<I', total_len))
        outfile.write(binary_msg)

        print(f"✅ Row {i} written — payload: {total_len} bytes")
