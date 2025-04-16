from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
import shutil

app = Flask(__name__)
UPLOAD_FOLDER = tempfile.mkdtemp()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

# Helper to extract folder structure
def get_folder_structure(root_path):
    structure = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        rel_dir = os.path.relpath(dirpath, root_path)
        structure.append({
            'path': rel_dir,
            'folders': dirnames,
            'files': filenames
        })
    return structure

# Safe extraction to prevent zip slip
def safe_extract(zip_ref, extract_path):
    for member in zip_ref.namelist():
        member_path = os.path.abspath(os.path.join(extract_path, member))
        if not member_path.startswith(os.path.abspath(extract_path)):
            raise Exception("Unsafe ZIP file detected!")
    zip_ref.extractall(extract_path)

@app.route('/upload', methods=['POST'])
def upload_zip():
    if 'zipfile' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['zipfile']
    filename = secure_filename(file.filename)
    extract_path = os.path.join(app.config['UPLOAD_FOLDER'], filename + '_extracted')
    os.makedirs(extract_path, exist_ok=True)
    zip_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(zip_path)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        try:
            safe_extract(zip_ref, extract_path)
        except Exception as e:
            # Clean up extracted files if unsafe
            shutil.rmtree(extract_path, ignore_errors=True)
            return jsonify({'error': str(e)}), 400
    structure = get_folder_structure(extract_path)
    return jsonify({'extract_path': extract_path, 'structure': structure})

@app.route('/search', methods=['POST'])
def search_xml():
    data = request.json
    extract_path = data.get('extract_path')
    folder = data.get('folder')
    keywords = data.get('keywords', [])
    attributes = data.get('attributes', [])
    not_endings = [s.lower() for s in data.get('not_endings', [])]
    startings = [s for s in data.get('startings', [])]
    # Always include these two fields
    default_fields = ['ReferencingAttributeName', 'ReferencedEntityName']
    all_fields = list(set(attributes) | set(default_fields))
    if not (extract_path and folder):
        return jsonify({'error': 'Missing parameters'}), 400
    search_path = os.path.join(extract_path, folder)
    results = []
    for root, _, files in os.walk(search_path):
        for file in files:
            if file.lower().endswith('.xml'):
                file_path = os.path.join(root, file)
                try:
                    tree = ET.parse(file_path)
                    root_elem = tree.getroot()
                    # Iterate over each EntityRelationship
                    for entity_rel in root_elem.findall('.//EntityRelationship'):
                        entity_text = ET.tostring(entity_rel, encoding='unicode')
                        if all(kw.lower() in entity_text.lower() for kw in keywords):
                            referencing_attr_elem = entity_rel.find('ReferencingAttributeName')
                            referencing_attr = referencing_attr_elem.text if referencing_attr_elem is not None else ''
                            # Apply 'must start with' filter if provided
                            if startings and not any(referencing_attr.startswith(prefix) for prefix in startings):
                                continue
                            # Apply 'must NOT end with' filter if provided
                            if not_endings and any(referencing_attr.lower().endswith(ending) for ending in not_endings):
                                continue
                            result = {'file': os.path.relpath(file_path, extract_path)}
                            for field in all_fields:
                                elem = entity_rel.find(field)
                                result[field] = elem.text if elem is not None else None
                            results.append(result)
                except Exception as e:
                    continue
    return jsonify({'results': results})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    # Run app on all interfaces (0.0.0.0) and the specified port
    app.run(host='0.0.0.0', port=port, debug=True)
