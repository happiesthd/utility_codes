import chardet

file_path = 'your_file_path_here.csv'

with open(file_path, 'rb') as f:
    raw_data = f.read(100000)  
result = chardet.detect(raw_data)
print(f"Detected encoding: {result['encoding']} with confidence {result['confidence']}")
