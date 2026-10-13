import os
from flask import Blueprint, render_template, request, redirect, jsonify, make_response, current_app
from flask_login import current_user, login_required
from models.user import db, Partner, PartnerConversion

partners_bp = Blueprint("partners", __name__)
PARTNER_COMMISSION_USD = float(os.getenv("PARTNER_COMMISSION_USD", "3.0"))


@partners_bp.route("/")
def dashboard():
    partner = None
    if current_user.is_authenticated:
        partner = Partner.query.filter_by(user_id=current_user.id).first()
    recent_conversions = []
    if partner:
        recent_conversions = (
            PartnerConversion.query
            .filter_by(partner_id=partner.id)
            .order_by(PartnerConversion.created_at.desc())
            .limit(10)
            .all()
        )
    base_url = request.host_url.rstrip("/")
    return render_template(
        "partners.html",
        partner=partner,
        recent_conversions=recent_conversions,
        base_url=base_url,
        commission=PARTNER_COMMISSION_USD,
    )


@partners_bp.route("/join", methods=["POST"])
@login_required
def join():
    existing = Partner.query.filter_by(user_id=current_user.id).first()
    if existing:
        return jsonify({"status": "already_partner", "code": existing.referral_code}), 200
    body = (request.json or {}) if request.is_json else {}
    social_handle  = body.get("social_handle",  "").strip()[:120]
    channel_url    = body.get("channel_url",    "").strip()[:300]
    platform       = body.get("platform",       "").strip()[:50]
    payout_method  = body.get("payout_method",  "").strip()[:20]
    payout_info    = body.get("payout_info",    "").strip()[:300]

    _VALID_PM = {"upi", "paypal", "bank", "crypto"}
    if payout_method not in _VALID_PM:
        payout_method = None

    partner = Partner(
        user_id=current_user.id,
        social_handle=social_handle or channel_url or None,
        channel_url=channel_url or None,
        platform=platform or None,
        payout_method=payout_method or None,
        payout_info=payout_info or None,
    )
    db.session.add(partner)
    db.session.commit()
    current_app.logger.info("[PARTNERS] New partner user_id=%s code=%s payout=%s",
                            current_user.id, partner.referral_code, payout_method)
    return jsonify({"status": "joined", "code": partner.referral_code}), 201



def _track_click_and_redirect(code):
    partner = Partner.query.filter_by(referral_code=code.upper(), is_active=True).first()
    if partner:
        partner.total_clicks += 1
        db.session.commit()
        current_app.logger.info("[PARTNERS] Click code=%s total=%d", code, partner.total_clicks)
    response = make_response(redirect("/"))
    response.set_cookie("hs_ref", code.upper(), max_age=30*24*3600, httponly=True, samesite="Lax", path="/")
    return response


@partners_bp.route("/click/<code>")
def click(code):
    return _track_click_and_redirect(code)


@partners_bp.route("/api/stats")
@login_required
def stats():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        return jsonify({"error": "not_a_partner"}), 404
    base_url = request.host_url.rstrip("/")
    return jsonify({
        "code": partner.referral_code,
        "referral_url": f"{base_url}/vip/{partner.referral_code}",
        "clicks": partner.total_clicks,
        "signups": partner.total_signups,
        "conversions": partner.total_conversions,
        "wallet_usd": round(partner.wallet_usd, 2),
        "total_earned_usd": round(partner.total_earned_usd, 2),
        "commission_per_sale": PARTNER_COMMISSION_USD,
    })


def credit_partner_for_code(referral_code, new_user_id, plan_name, stripe_session_id=None):
    """Credit the partner whose referral_code matches. ALWAYS logs outcome per AGENTS.md."""
    import logging
    logger = logging.getLogger(__name__)
    if not referral_code:
        logger.info("[PARTNERS] credit_partner_for_code: no code, skipping.")
        return False
    partner = Partner.query.filter_by(referral_code=referral_code.upper(), is_active=True).first()
    if not partner:
        logger.warning("[PARTNERS] credit_partner_for_code: code=%r not found or inactive.", referral_code)
        return False
    commission = PARTNER_COMMISSION_USD
    partner.wallet_usd = round(partner.wallet_usd + commission, 2)
    partner.total_earned_usd = round(partner.total_earned_usd + commission, 2)
    partner.total_conversions += 1
    partner.total_signups += 1
    conversion = PartnerConversion(
        partner_id=partner.id,
        converted_user_id=new_user_id,
        plan_name=plan_name,
        amount_usd=commission,
        stripe_session_id=stripe_session_id,
    )
    db.session.add(conversion)
    db.session.commit()
    logger.info("[PARTNERS] Credited code=%s user=%s +$%.2f wallet=$%.2f",
                referral_code, partner.user_id, commission, partner.wallet_usd)
    return True



# -- Channel existence validator ----------------------------------------------
import re as _re
import requests as _req

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_RE   = _re.compile(r'youtube\.com/watch|youtu\.be/', _re.I)
_YT_CHAN_RE    = _re.compile(r'youtube\.com/@|youtube\.com/c/|youtube\.com/channel/|youtube\.com/user/', _re.I)
_TT_VIDEO_RE   = _re.compile(r'tiktok\.com/@[^/]+/video/', _re.I)
_TT_PROF_RE    = _re.compile(r'tiktok\.com/@', _re.I)
_IG_RE         = _re.compile(r'instagram\.com', _re.I)
_TW_RE         = _re.compile(r'twitter\.com|x\.com', _re.I)
_TWITCH_RE     = _re.compile(r'twitch\.tv', _re.I)
_TITLE_RE      = _re.compile(r'<title[^>]*>([^<]+)</title>', _re.I)
_OG_TITLE_RE   = _re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', _re.I)


def _extract_title(html):
    m = _OG_TITLE_RE.search(html)
    if m: return m.group(1).strip()
    m = _TITLE_RE.search(html)
    if m: return m.group(1).strip()
    return ''


def _extract_handle(url):
    parts = url.rstrip('/').split('/')
    slug = parts[-1] if parts else ''
    return ('@' + slug.lstrip('@')) if slug and slug != '.' else ''


def _head_check(url, platform, name_fallback=''):
    try:
        r = _req.head(url, headers=_HEADERS, timeout=7, allow_redirects=True)
        if r.status_code < 400:
            name = name_fallback or _extract_handle(url) or url
            return {'exists': True, 'name': name, 'thumb': '', 'platform': platform}
        if r.status_code in (405, 403):
            r2 = _req.get(url, headers=_HEADERS, timeout=8, stream=True)
            chunk = next(r2.iter_content(8192), b'')
            r2.close()
            if r2.status_code < 400:
                title = _extract_title(chunk.decode('utf-8', errors='ignore'))
                name  = title or name_fallback or _extract_handle(url) or url
                return {'exists': True, 'name': name, 'thumb': '', 'platform': platform}
            return {'exists': False, 'error': 'HTTP ' + str(r2.status_code)}
        return {'exists': False, 'error': 'HTTP ' + str(r.status_code)}
    except Exception as e:
        return {'exists': False, 'error': str(e)[:120]}


def _oembed_youtube(url):
    try:
        r = _req.get('https://www.youtube.com/oembed?url=' + url + '&format=json',
                     headers=_HEADERS, timeout=7)
        if r.status_code == 200:
            d = r.json()
            return {'exists': True,
                    'name':  d.get('author_name') or d.get('title', ''),
                    'thumb': d.get('thumbnail_url', ''),
                    'platform': 'YouTube'}
        return {'exists': False, 'error': 'oEmbed ' + str(r.status_code)}
    except Exception as e:
        return {'exists': False, 'error': str(e)[:120]}


def _oembed_tiktok(url):
    try:
        r = _req.get('https://www.tiktok.com/oembed?url=' + url,
                     headers=_HEADERS, timeout=7)
        if r.status_code == 200 and r.text.strip():
            d = r.json()
            return {'exists': True,
                    'name':  d.get('author_name') or d.get('title', ''),
                    'thumb': d.get('thumbnail_url', ''),
                    'platform': 'TikTok'}
        return {'exists': False, 'error': 'oEmbed ' + str(r.status_code)}
    except Exception as e:
        return {'exists': False, 'error': str(e)[:120]}


@partners_bp.route('/api/validate-channel', methods=['POST'])
def validate_channel():
    """
    POST { 'url': 'https://youtube.com/@TJR_Official' }
    Returns { 'exists': bool, 'name': str, 'thumb': str, 'platform': str }
    No auth required.
    """
    body = (request.json or {}) if request.is_json else {}
    url  = (body.get('url') or '').strip()
    if not url or len(url) < 8:
        return jsonify({'exists': False, 'error': 'No URL provided'}), 400
    if not url.startswith('http'):
        url = 'https://' + url
    current_app.logger.info('[PARTNERS] validate-channel url=%s', url)

    if _YT_VIDEO_RE.search(url):
        result = _oembed_youtube(url)
    elif _YT_CHAN_RE.search(url):
        # Channel page: try HEAD then GET+parse title
        result = _head_check(url, 'YouTube')
        if not result['exists']:
            try:
                resp = _req.get(url, headers=_HEADERS, timeout=8, stream=True)
                chunk = next(resp.iter_content(16384), b'')
                resp.close()
                if resp.status_code < 400:
                    title = _extract_title(chunk.decode('utf-8', errors='ignore'))
                    result = {'exists': True, 'name': title or _extract_handle(url),
                              'thumb': '', 'platform': 'YouTube'}
            except Exception:
                pass
    elif _TT_VIDEO_RE.search(url):
        result = _oembed_tiktok(url)
    elif _TT_PROF_RE.search(url):
        result = _head_check(url, 'TikTok')
    elif _IG_RE.search(url):
        result = _head_check(url, 'Instagram')
    elif _TW_RE.search(url):
        result = _head_check(url, 'Twitter/X')
    elif _TWITCH_RE.search(url):
        result = _head_check(url, 'Twitch')
    else:
        return jsonify({'exists': False, 'error': 'Unrecognised platform'}), 422

    status = 200 if result.get('exists') else 404
    current_app.logger.info('[PARTNERS] validate-channel result=%s', result)
    return jsonify(result), status
