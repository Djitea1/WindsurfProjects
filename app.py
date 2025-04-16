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
    # Always include these fields
    default_fields = ['ReferencingAttributeName', 'ReferencedEntityName', 'ReferencingEntityName']
    all_fields = list(set(attributes) | set(default_fields))
    if not (extract_path and folder):
        return jsonify({'error': 'Missing parameters'}), 400
    search_path = os.path.join(extract_path, folder)
    results = []
    
    # Debug info
    print(f"Search params: keywords={keywords}, not_endings={not_endings}, startings={startings}")
    
    for root, _, files in os.walk(search_path):
        for file in files:
            if file.lower().endswith('.xml'):
                file_path = os.path.join(root, file)
                print(f"Processing file: {file_path}")
                try:
                    tree = ET.parse(file_path)
                    root_elem = tree.getroot()
                    
                    # Process each EntityRelationship
                    found_in_file = False
                    for entity_rel in root_elem.findall('.//EntityRelationship'):
                        # Check keywords if provided
                        if keywords:
                            entity_text = ET.tostring(entity_rel, encoding='unicode').lower()
                            if not all(kw.lower() in entity_text for kw in keywords):
                                continue
                        
                        # Get ReferencingAttributeName - this is critical for filtering
                        ref_attr_elem = entity_rel.find('ReferencingAttributeName')
                        if ref_attr_elem is None or ref_attr_elem.text is None:
                            continue
                        ref_attr = ref_attr_elem.text
                        
                        print(f"  Found attribute: {ref_attr}")
                        
                        # Check 'must start with' filter
                        if startings:
                            if not any(ref_attr.startswith(prefix) for prefix in startings):
                                print(f"  Skipping - doesn't start with any of {startings}")
                                continue
                        
                        # Check 'must NOT end with' filter
                        if not_endings:
                            should_skip = False
                            for ending in not_endings:
                                if ref_attr.lower().endswith(ending.lower()):
                                    print(f"  Skipping - ends with '{ending}'")
                                    should_skip = True
                                    break
                            if should_skip:
                                continue
                        
                        # If we got here, this EntityRelationship passed all filters
                        found_in_file = True
                        result = {'file': os.path.relpath(file_path, extract_path)}
                        for field in all_fields:
                            elem = entity_rel.find(field)
                            result[field] = elem.text if elem is not None else None
                        results.append(result)
                        print(f"  Added to results: {result}")
                    
                    if not found_in_file:
                        print(f"  No matching relationships in file")
                        
                except Exception as e:
                    print(f"  Error processing file: {str(e)}")
                    continue
    
    print(f"Total results: {len(results)}")
    return jsonify({'results': results})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Test function to verify filtering logic
def test_filtering():
    # Sample XML content similar to what the user provided
    test_xml = '''<?xml version="1.0" encoding="utf-8"?>
<EntityRelationships xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <EntityRelationship Name="mmpl_disputemember_Contact_contact">
    <EntityRelationshipType>OneToMany</EntityRelationshipType>
    <ReferencingEntityName>mmpl_DisputeMember</ReferencingEntityName>
    <ReferencedEntityName>Contact</ReferencedEntityName>
    <ReferencingAttributeName>mmpl_Contact</ReferencingAttributeName>
  </EntityRelationship>
  <EntityRelationship Name="mmpl_disputememberemployment_ContactId_contact">
    <EntityRelationshipType>OneToMany</EntityRelationshipType>
    <ReferencingEntityName>mmpl_DisputeMemberEmployment</ReferencingEntityName>
    <ReferencedEntityName>Contact</ReferencedEntityName>
    <ReferencingAttributeName>mmpl_ContactId</ReferencingAttributeName>
  </EntityRelationship>
  <EntityRelationship Name="mmpl_disputeaccount_EmployerId_account">
    <EntityRelationshipType>OneToMany</EntityRelationshipType>
    <ReferencingEntityName>mmpl_DisputeAccount</ReferencingEntityName>
    <ReferencedEntityName>Account</ReferencedEntityName>
    <ReferencingAttributeName>mmpl_EmployerId</ReferencingAttributeName>
  </EntityRelationship>
</EntityRelationships>'''
    
    # Create a temporary file with the test XML
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
        f.write(test_xml.encode('utf-8'))
        test_file = f.name
    
    try:
        # Parse the XML
        tree = ET.parse(test_file)
        root = tree.getroot()
        
        # Test cases
        test_cases = [
            {
                "name": "No filters",
                "keywords": [],
                "not_endings": [],
                "startings": [],
                "expected_count": 3,
                "expected_attrs": ["mmpl_Contact", "mmpl_ContactId", "mmpl_EmployerId"]
            },
            {
                "name": "Filter by ending with 'Id'",
                "keywords": [],
                "not_endings": ["Id"],
                "startings": [],
                "expected_count": 1,
                "expected_attrs": ["mmpl_Contact"]
            },
            {
                "name": "Filter by starting with 'mmpl_'",
                "keywords": [],
                "not_endings": [],
                "startings": ["mmpl_"],
                "expected_count": 3,
                "expected_attrs": ["mmpl_Contact", "mmpl_ContactId", "mmpl_EmployerId"]
            },
            {
                "name": "Combined filters",
                "keywords": [],
                "not_endings": ["Id"],
                "startings": ["mmpl_"],
                "expected_count": 1,
                "expected_attrs": ["mmpl_Contact"]
            }
        ]
        
        # Run tests
        for test in test_cases:
            results = []
            
            for entity_rel in root.findall('.//EntityRelationship'):
                # Convert to string for keyword search
                if test["keywords"]:
                    entity_text = ET.tostring(entity_rel, encoding='unicode').lower()
                    if not all(kw.lower() in entity_text for kw in test["keywords"]):
                        continue
                
                # Get ReferencingAttributeName
                ref_attr_elem = entity_rel.find('ReferencingAttributeName')
                if ref_attr_elem is None or ref_attr_elem.text is None:
                    continue
                ref_attr = ref_attr_elem.text
                
                # Apply 'must start with' filter
                if test["startings"] and not any(ref_attr.startswith(prefix) for prefix in test["startings"]):
                    continue
                
                # Apply 'must NOT end with' filter
                if test["not_endings"]:
                    should_skip = False
                    for ending in test["not_endings"]:
                        if ref_attr.lower().endswith(ending.lower()):
                            should_skip = True
                            break
                    if should_skip:
                        continue
                
                # If we got here, this passed all filters
                results.append(ref_attr)
            
            # Verify results
            print(f"Test: {test['name']}")
            print(f"  Found: {len(results)}, Expected: {test['expected_count']}")
            print(f"  Results: {results}")
            print(f"  Expected: {test['expected_attrs']}")
            
            assert len(results) == test["expected_count"], f"Test failed: {test['name']}"
            for attr in test["expected_attrs"]:
                assert attr in results, f"Missing expected attribute: {attr}"
        
        print("All tests passed!")
        return True
    
    except Exception as e:
        print(f"Test error: {e}")
        return False
    finally:
        # Clean up
        os.unlink(test_file)

if __name__ == '__main__':
    # Run tests in development mode
    if os.environ.get('FLASK_ENV') == 'development':
        test_filtering()
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    # Run app on all interfaces (0.0.0.0) and the specified port
    app.run(host='0.0.0.0', port=port, debug=True)
