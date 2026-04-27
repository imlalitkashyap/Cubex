import os
import requests
import json
import re
import html
import time
import base64
import urllib.parse
from urllib.parse import urlparse

# ==========================================
# 💎 SECURE PRO MATRIX CONFIGURATION 💎
# ==========================================
# Tokens ab GitHub Secrets se aayenge (Public Code mein nahi dikhenge)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "").strip()
GITHUB_TOKEN = os.environ.get("GH_PAT", "").strip()

# Sirf ye public rahega:
GITHUB_USERNAME = "imlalitkashyap" # UPDATE THIS
GITHUB_REPO = "Tests" # Teri Private Data repo ka naam
GITHUB_FOLDER = "data"

TEST_SERIES_LINK = os.environ.get("SERIES_LINK", "").strip()
CHUNK_SIZE = 150 
# ==========================================

class MatrixExtractor:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.headers = {
            "authorization": f"Bearer {self.auth_token}",
            "x-tb-client": "web,1.2",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def fetch(self, url, params=None, method='GET', json_data=None):
        for _ in range(3):
            try:
                time.sleep(0.8) 
                if method == 'GET':
                    resp = requests.get(url, headers=self.headers, params=params, timeout=30)
                else:
                    resp = requests.post(url, headers=self.headers, params=params, json=json_data, timeout=30)
                if resp.status_code in [400, 401, 403, 404]: return None
                if resp.json().get('success'): return resp.json()
            except: time.sleep(3)
        return None

    def get_slug(self, url):
        path = urlparse(url).path.strip('/').split('/')
        if 'test-series' in path: return path[path.index('test-series') - 1]
        return path[-1]

    def clean(self, txt):
        if isinstance(txt, dict): txt = txt.get('text', txt.get('value', ''))
        txt = str(txt or "")
        match = re.search(r"'value':\s*'([^']*)'", txt)
        if match: txt = match.group(1)
        return re.sub(r'src="//', 'src="https://', html.unescape(txt))

    def build_json(self, t_en, a_en, t_hn, a_hn):
        q_data, a_data = t_en['data'], a_en['data']
        q_hn, a_hn = t_hn.get('data', q_data), a_hn.get('data', a_data)
        quiz = {"test_id": q_data['_id'], "title": {"en": q_data.get('title',''), "hn": q_hn.get('title','')}, "total_questions": 0, "sections": []}
        for sec_e, sec_h in zip(q_data.get('sections',[]), q_hn.get('sections',[])):
            s = {"section_id": sec_e['_id'], "title": {"en": sec_e.get('title',''), "hn": sec_h.get('title','')}, "questions": []}
            for qe, qh in zip(sec_e.get('questions',[]), sec_h.get('questions',[])):
                qid = qe['_id']
                ae, ah = a_data.get(qid, {}), a_hn.get(qid, {})
                s['questions'].append({
                    "question_id": qid,
                    "content": {"en": self.clean(qe.get('en',{}).get('value','')), "hn": self.clean(qh.get('hn',{}).get('value',''))},
                    "options": {"en": [self.clean(o) for o in qe.get('en',{}).get('options',[])], "hn": [self.clean(o) for o in qh.get('hn',{}).get('options',[])]},
                    "correct_answer": ae.get('correctOption',''),
                    "solution": {"en": {"text": self.clean(ae.get('sol',{}).get('en',{}).get('value',''))}, "hn": {"text": self.clean(ah.get('sol',{}).get('hn',{}).get('value',''))}}
                })
            quiz['sections'].append(s)
            quiz['total_questions'] += len(s['questions'])
        return quiz

def upload_with_retry(folder_name, filename, content):
    path = f"{GITHUB_FOLDER}/{folder_name}/{filename}"
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{urllib.parse.quote(path)}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    for attempt in range(5):
        try:
            sha_resp = requests.get(url, headers=headers)
            sha = sha_resp.json().get('sha') if sha_resp.status_code == 200 else None
            
            data = {"message": f"Added {filename} to {folder_name}", "content": base64.b64encode(json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')).decode('utf-8')}
            if sha: data["sha"] = sha
            
            res = requests.put(url, headers=headers, json=data)
            
            if res.status_code in [200, 201]: return True, ""
            elif res.status_code in [409, 403, 429]: time.sleep(3)
            else: return False, res.text
        except Exception as e: time.sleep(3)
    return False, "Max Retries Reached"

def run():
    if not AUTH_TOKEN or not GITHUB_TOKEN:
        print("❌ CRITICAL ERROR: Auth Token ya GitHub PAT Secrets mein missing hai!")
        return
        
    if not TEST_SERIES_LINK: return
        
    ext = MatrixExtractor(AUTH_TOKEN)
    slug = ext.get_slug(TEST_SERIES_LINK)
    details = ext.fetch(f"https://api.testbook.com/api/v1/test-series/slug?url={slug}&language=English")
    
    if not details: return
    details = details['data']['details']
    print(f"🚀 Started: {details['name']}")
    
    tids = []
    for sec in details.get('sections',[]):
        for sub in (sec.get('subsections',[]) or [{'id':""}]):
            res = ext.fetch(f"https://api.testbook.com/api/v2/test-series/{details['id']}/tests/details?testType=all&sectionId={sec['id']}&subSectionId={sub.get('id','')}&skip=0&limit=9999&language=English")
            if res:
                for t in res['data']['tests']:
                    tid = t.get('testId', t.get('id'))
                    if tid and tid not in tids: tids.append(tid)

    total_tests = len(tids)
    print(f"🎯 Total Tests: {total_tests}")
    
    master = {"series_id": details['id'], "series_name": details['name'], "tests": []}
    part_num = 1
    extracted_total = 0
    
    clean_series_name = re.sub(r'[^a-zA-Z0-9 ]', '', details['name']).strip()
    folder_name = f"✅ {clean_series_name}"
    base_filename = clean_series_name.replace(' ', '_')

    for i, tid in enumerate(tids, 1):
        q_en = ext.fetch(f"https://api-new.testbook.com/api/v2/tests/{tid}", params={"auth_code": AUTH_TOKEN, "language": "English"})
        if not q_en: continue
        q_hn = ext.fetch(f"https://api-new.testbook.com/api/v2/tests/{tid}", params={"auth_code": AUTH_TOKEN, "language": "Hindi"})
        ext.submit(tid)
        time.sleep(0.8)
        
        a_en = ext.fetch(f"https://api-new.testbook.com/api/v2/tests/{tid}/answers", params={"auth_code": AUTH_TOKEN, "language": "English"})
        if not a_en: continue
        a_hn = ext.fetch(f"https://api-new.testbook.com/api/v2/tests/{tid}/answers", params={"auth_code": AUTH_TOKEN, "language": "Hindi"})
        
        quiz = ext.build_json(q_en, a_en, q_hn or q_en, a_hn or a_en)
        if quiz['total_questions'] > 0: 
            master["tests"].append(quiz)
            extracted_total += 1
            
        if i % 10 == 0: print(f"🔄 {details['name']}: {i}/{total_tests} fetched...")

        if len(master["tests"]) == CHUNK_SIZE or i == total_tests:
            if len(master["tests"]) > 0:
                master["total_tests"] = len(master["tests"])
                filename = f"{base_filename}_Part_{part_num}.json" if total_tests > CHUNK_SIZE else f"{base_filename}.json"
                
                print(f"🚀 Uploading {filename} to '{folder_name}'...")
                success, err_msg = upload_with_retry(folder_name, filename, master)
                if success: print(f"✅ SAVED: {folder_name}/{filename}")
                else: print(f"❌ UPLOAD FAILED: {err_msg}")
                
                master["tests"] = []
                part_num += 1
                
        time.sleep(0.3)

    print(f"\n🎉 TOTAL COMPLETED: {extracted_total}/{total_tests} tests!")

if __name__ == "__main__": run()
