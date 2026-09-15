"""In-page extractors anchored on href patterns, not hashed CSS classes."""

MAIN_JS = "() => { const m = document.querySelector('main'); return (m ? m.innerText : (document.body ? document.body.innerText : '')) || ''; }"

PEOPLE_JS = r"""
() => {
  const seen = new Map();
  document.querySelectorAll('a[href*="/in/"]').forEach(a => {
    const href = (a.getAttribute('href') || '').split('?')[0];
    const m = href.match(/\/in\/([^/]+)\/?$/);
    if (!m) return;
    const username = decodeURIComponent(m[1]);
    if (username === 'me') return;
    const name = (a.innerText || '').trim().split('\n')[0].trim();
    if (!seen.has(username)) {
      seen.set(username, { username, name: '', profile_url: 'https://www.linkedin.com/in/' + username + '/' });
    }
    const rec = seen.get(username);
    if (!rec.name && name && !/^https?:/i.test(name)) rec.name = name;
  });
  return [...seen.values()].filter(r => r.name).slice(0, 30);
}
"""

JOBS_JS = r"""
() => {
  const seen = new Map();
  document.querySelectorAll('a[href*="/jobs/view/"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/\/jobs\/view\/(\d+)/);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    const li = a.closest('li') || a.parentElement;
    const lines = (((li && li.innerText) || a.innerText || '')).split('\n').map(s => s.trim()).filter(Boolean);
    const dedup = [];
    for (const s of lines) {
      const prev = dedup[dedup.length - 1];
      if (prev === s || s === prev + ' with verification') continue;
      dedup.push(s);
    }
    const network = dedup.find(s => /alumni work here|connections? work here/i.test(s)) || '';
    const isBadge = s => /^(Promoted|Easy Apply|Viewed|Reposted|Actively reviewing applicants|Be an early applicant|Hybrid|Remote|On-site)$/i.test(s);
    const badges = dedup.filter(isBadge);
    const core = dedup.filter(s => !isBadge(s) && s !== network);
    seen.set(id, {
      job_id: id, title: core[0] || '', company: core[1] || '', location: core[2] || '',
      network, badges, url: 'https://www.linkedin.com/jobs/view/' + id + '/'
    });
  });
  return [...seen.values()].slice(0, 25);
}
"""

MESSAGES_JS = r"""
() => {
  return [...document.querySelectorAll('li[class*="msg-conversation"]')].map(li => {
    const lines = (li.innerText || '').split('\n').map(s => s.trim()).filter(Boolean)
      .filter(s => !/^\.\s/.test(s) && !/^Status is /i.test(s) && !/^Open the options list/i.test(s) && s.toLowerCase() !== 'active conversation');
    const name = lines[0] || '';
    const snippet = lines.find(s => s.length > 25) || lines[lines.length - 1] || '';
    const is_inmail = /^InMail/.test(snippet);
    const is_sponsored = /^Sponsored/.test(snippet);
    return {
      name, date: lines[1] || '',
      snippet: snippet.replace(/^(InMail|Sponsored)\s*/, ''),
      is_inmail, is_sponsored,
    };
  }).filter(r => r.name).slice(0, 25);
}
"""

THREAD_JS = "() => { const p = document.querySelector('.msg-s-message-list-container, .msg-s-message-list, .msg-thread') || document.querySelector('main') || document.body; return (p ? p.innerText : '') || ''; }"

THREAD_SCROLL_JS = "() => { const p = document.querySelector('.msg-s-message-list-container, .msg-s-message-list'); if (p) p.scrollTop = 0; }"
