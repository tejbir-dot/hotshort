"""
HotShort Partner Automation Engine
----------------------------------
Behavioral Automation Loop & Dopamine Triggers:
1. Micro-Win Trigger: Instant click & signup momentum dopamine emails.
2. Loss Aversion Trigger: Pending Vault at-risk reminder with fresh hook injection.
3. Status Update Trigger: Next-tier gravity nudge (e.g. 2 paid subs away from Silver).
4. Conversion Trigger: Paid subscription cha-ching notification.

Built with asynchronous non-blocking thread execution and graceful SMTP failover.
"""

import os
import sys
import smtplib
import logging
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Curated high-converting viral hooks for loss aversion emails
CURATED_VIRAL_HOOKS = [
    "Stop paying video editors $50 a clip. Look at what this AI tool did in 30 seconds...",
    "How faceless channels are making $3k/month using this secret podcast clip generator...",
    "The AI tool every short-form creator is secretly using to post 5x a day on autopilot...",
    "Watch me turn a boring 45-minute YouTube interview into 10 viral TikToks in 60 seconds...",
    "If you're still manually cutting podcast shorts in 2026, stop scrolling right now...",
]


class PartnerAutomationEngine:
    def __init__(self):
        self.smtp_user = os.getenv("SMTP_USER", "partners@hotshort.ai")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.app_base_url = (os.getenv("BASE_URL") or os.getenv("APP_URL") or "https://app.hotshort.ai").rstrip("/")
        self.executor = ThreadPoolExecutor(max_workers=3)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. CORE EMAIL SENDER (ASYNC + GRACEFUL FALLBACK)
    # ─────────────────────────────────────────────────────────────────────────
    def _send_email_async(self, to_email: str, subject: str, body_text: str, body_html: str = None):
        """Submit email send to thread pool to avoid blocking web requests."""
        if not to_email or "@" not in to_email:
            logger.warning("[PARTNER AUTOMATION] Invalid email %r, skipping send", to_email)
            return False
        self.executor.submit(self._send_smtp_sync, to_email, subject, body_text, body_html)
        return True

    def _send_smtp_sync(self, to_email: str, subject: str, body_text: str, body_html: str = None):
        """Synchronous SMTP worker running inside background thread."""
        try:
            if not self.smtp_pass or self.smtp_pass.strip().lower() in ("placeholder", "none", ""):
                # Local dev / test environment logging
                logger.info("[PARTNER AUTOMATION (DEV/MOCK)] Target: %s | Subject: %s", to_email, subject)
                try:
                    sys_out = getattr(sys, "stdout", None)
                    enc = getattr(sys_out, "encoding", "utf-8") or "utf-8"
                    safe_sub = subject.encode(enc, errors="replace").decode(enc)
                    safe_body = body_text.encode(enc, errors="replace").decode(enc)
                    print(f"\n=======================================================\n"
                          f"[PARTNER AUTOMATION DEV NOTIFICATION]\n"
                          f"To: {to_email}\n"
                          f"Subject: {safe_sub}\n"
                          f"-------------------------------------------------------\n"
                          f"{safe_body}\n"
                          f"=======================================================\n")
                except Exception:
                    pass
                return True

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = formataddr(("HotShort Partner Network", self.smtp_user))
            msg["To"] = to_email
            msg.set_content(body_text)

            if body_html:
                msg.add_alternative(body_html, subtype="html")

            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=12)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=12)
                server.starttls()

            server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)
            server.quit()
            logger.info("[PARTNER AUTOMATION] Successfully sent email to %s (Subject: %s)", to_email, subject)
            return True
        except Exception as e:
            logger.error("[PARTNER AUTOMATION] Failed to send email to %s: %s", to_email, e)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # 2. TRIGGER: MICRO-WIN LINK CLICK DOPAMINE
    # ─────────────────────────────────────────────────────────────────────────
    def on_link_clicked(self, referral_code: str, request_meta: dict = None):
        """
        Fires on referral link click.
        Updates partner metrics, records activity log, and dispatches micro-win dopamine email
        for milestones (1, 10, 25, 50, 100...) or after a 4h cooldown.
        """
        from models.user import db, Partner, PartnerActivityLog
        from routes.partners import calculate_pending_potential

        if not referral_code:
            return

        partner = Partner.query.filter_by(referral_code=referral_code.upper(), is_active=True).first()
        if not partner:
            return

        now = datetime.utcnow()
        partner.total_clicks += 1
        partner.last_click_at = now

        pending_potential = calculate_pending_potential(
            partner.total_signups, partner.total_conversions, partner.total_clicks
        )

        # Activity log
        log_entry = PartnerActivityLog(
            partner_id=partner.id,
            event_type="click",
            icon="🖱️",
            title=f"Link Click #{partner.total_clicks} Detected",
            description=f"Traffic is warming up! Potential kinetic energy in funnel.",
            potential_usd=pending_potential,
            email_sent=False,
            created_at=now,
        )
        db.session.add(log_entry)

        # Milestone email check: 1st, 10th, 25th, 50th, 100th, 250th...
        is_milestone = partner.total_clicks in (1, 10, 25, 50, 100, 250, 500, 1000)
        cooldown_passed = (
            partner.last_click_email_at is None
            or (now - partner.last_click_email_at) > timedelta(hours=4)
        )

        if (is_milestone or cooldown_passed) and partner.user and partner.user.email:
            subject = f"🔥 Someone just clicked your link! Your pipeline is warming up"
            partner.last_click_email_at = now
            log_entry.email_sent = True

            dashboard_url = f"{self.app_base_url}/partners/"
            body_text = (
                f"🔥 Someone just clicked your HotShort link!\n\n"
                f"Your pipeline is warming up. A creator just tapped your referral link and entered your funnel.\n\n"
                f"📊 Current Momentum:\n"
                f"• Link Clicks: {partner.total_clicks}\n"
                f"• Free Signups: {partner.total_signups}\n"
                f"• Projected Pending Vault: +${pending_potential:.2f}/mo\n\n"
                f"💡 The Flywheel Secret:\n"
                f"Post one more video today while your traffic is active to push these viewers into free trials!\n\n"
                f"👉 Grab today's ready-to-post script & ASMR B-Roll:\n"
                f"{dashboard_url}\n"
            )
            body_html = self._render_template_html(
                badge="🔥 TOP-OF-FUNNEL PULSE",
                title="Someone Just Clicked Your Link!",
                highlight=f"{partner.total_clicks} Clicks Driven",
                description=(
                    "Your kinetic energy is building! A creator just discovered HotShort through your VIP referral link. "
                    "Post one more video today while your traffic is hot to push them into a free trial."
                ),
                metrics=[
                    ("Link Clicks", str(partner.total_clicks)),
                    ("Free Signups", str(partner.total_signups)),
                    ("Pending Vault", f"+${pending_potential:.2f}/mo"),
                ],
                action_text="Open Creator Action Center →",
                action_url=dashboard_url,
            )
            self._send_email_async(partner.user.email, subject, body_text, body_html)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("[PARTNER AUTOMATION] Failed to commit click activity: %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. TRIGGER: MICRO-WIN FREE SIGNUP DOPAMINE
    # ─────────────────────────────────────────────────────────────────────────
    def on_user_signed_up(self, referral_code: str, new_user_id: int, new_user_email: str = None):
        """
        Fires the moment a user registers/authenticates for the first time with an active hs_ref cookie.
        Increments partner.total_signups, updates Pending Vault potential, and fires instant dopamine email.
        """
        from models.user import db, Partner, PartnerActivityLog
        from routes.partners import calculate_pending_potential

        if not referral_code:
            return

        partner = Partner.query.filter_by(referral_code=referral_code.upper(), is_active=True).first()
        if not partner:
            return

        now = datetime.utcnow()
        partner.total_signups += 1
        partner.last_signup_at = now

        pending_potential = calculate_pending_potential(
            partner.total_signups, partner.total_conversions, partner.total_clicks
        )

        log_entry = PartnerActivityLog(
            partner_id=partner.id,
            event_type="signup",
            icon="🎉",
            title="New Creator Free Signup!",
            description=f"A new creator joined via your link! Pending Vault grew to +${pending_potential:.2f}/mo.",
            potential_usd=pending_potential,
            email_sent=False,
            created_at=now,
        )
        db.session.add(log_entry)

        if partner.user and partner.user.email:
            subject = f"🎉 New Signup! Your Pending Vault just grew to +${pending_potential:.2f}/mo!"
            log_entry.email_sent = True

            dashboard_url = f"{self.app_base_url}/partners/"
            body_text = (
                f"🎉 High five! Someone just signed up via your link!\n\n"
                f"Your Pending Vault just increased to +${pending_potential:.2f}/mo in projected recurring MRR.\n\n"
                f"These users are currently inside HotShort testing the app and generating viral clips.\n"
                f"At our standard 10% conversion rate on the $15/mo plan, each active trial user compounds your monthly recurring revenue.\n\n"
                f"🎯 Your Next Move:\n"
                f"Drop one more clip or story today to keep your brand top-of-mind and lock them into a paid subscription!\n\n"
                f"👉 Check your live Pending Vault:\n"
                f"{dashboard_url}\n"
            )
            body_html = self._render_template_html(
                badge="🎉 PENDING WEALTH ACCUMULATED",
                title="New User Signed Up!",
                highlight=f"+${pending_potential:.2f}/mo Pending Vault",
                description=(
                    "A new creator registered via your link! They are currently testing the app and generating clips. "
                    "At our standard 10% conversion rate, this kinetic energy projects directly into compounding monthly recurring revenue."
                ),
                metrics=[
                    ("Free Signups", str(partner.total_signups)),
                    ("Pending Vault", f"+${pending_potential:.2f}/mo"),
                    ("Settled Wallet", f"${partner.wallet_usd:.2f}"),
                ],
                action_text="View Your Pending Vault →",
                action_url=dashboard_url,
            )
            self._send_email_async(partner.user.email, subject, body_text, body_html)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("[PARTNER AUTOMATION] Failed to commit signup activity: %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. TRIGGER: LOSS AVERSION NOTIFICATION ("The Vault is Leaking")
    # ─────────────────────────────────────────────────────────────────────────
    def check_and_send_loss_aversion_alerts(self, inactive_days: int = 3, min_cooldown_days: int = 5) -> int:
        """
        Scans for partners with pending potential whose pipeline is cooling down (>3 days inactive).
        Injects a fresh, ready-to-copy viral hook to reactivate their momentum.
        Returns count of emails sent.
        """
        from models.user import db, Partner, PartnerActivityLog
        from routes.partners import calculate_pending_potential

        now = datetime.utcnow()
        cutoff_activity = now - timedelta(days=inactive_days)
        cutoff_cooldown = now - timedelta(days=min_cooldown_days)

        active_partners = Partner.query.filter_by(is_active=True).all()
        sent_count = 0

        for partner in active_partners:
            # Must have non-converted trial users (free signups)
            free_signups = max(partner.total_signups - partner.total_conversions, 0)
            pending_potential = calculate_pending_potential(
                partner.total_signups, partner.total_conversions, partner.total_clicks
            )
            if pending_potential <= 0:
                continue

            # Check if inactive (last click and last signup both > inactive_days)
            last_activity = partner.last_signup_at or partner.last_click_at or partner.created_at
            if last_activity and last_activity > cutoff_activity:
                continue

            # Check cooldown since last loss aversion email
            if partner.last_loss_aversion_at and partner.last_loss_aversion_at > cutoff_cooldown:
                continue

            if not partner.user or not partner.user.email:
                continue

            # Rotate a fresh hook
            hook_idx = (partner.id + int(now.timestamp() // 86400)) % len(CURATED_VIRAL_HOOKS)
            fresh_hook = CURATED_VIRAL_HOOKS[hook_idx]

            subject = f"⚠️ You have ${pending_potential:.2f}/mo sitting in your Pending Vault..."
            dashboard_url = f"{self.app_base_url}/partners/"

            body_text = (
                f"⚠️ Don't let your momentum die!\n\n"
                f"You currently have ${pending_potential:.2f}/mo sitting in your Pending Vault from {free_signups} trial users.\n\n"
                f"Free trial users are most likely to upgrade during their first week. If you don't reinforce their intent, "
                f"that potential recurring revenue evaporates.\n\n"
                f"Here is a fresh, high-converting hook to post right now:\n"
                f"👉 \"{fresh_hook}\"\n\n"
                f"Download the weekly ASMR B-roll pack and post this hook in under 2 minutes:\n"
                f"{dashboard_url}\n"
            )
            body_html = self._render_template_html(
                badge="⚠️ LOSS AVERSION ALERT",
                title="Your Pending Vault is Cooling Down",
                highlight=f"${pending_potential:.2f}/mo at Risk",
                description=(
                    f"You have <strong>${pending_potential:.2f}/mo</strong> sitting in your Pending Vault from {free_signups} trial creators. "
                    "Creators who post a follow-up clip within 48 hours convert 3.4x more trial users into permanent monthly cashflow. "
                    "Don't let this recurring revenue slip away."
                ),
                metrics=[
                    ("Pending Vault", f"${pending_potential:.2f}/mo"),
                    ("Active Trials", str(free_signups)),
                    ("Next Tier Cut", "30% Lifetime MRR"),
                ],
                fresh_hook=fresh_hook,
                action_text="Claim Your Pending Wealth →",
                action_url=dashboard_url,
            )

            partner.last_loss_aversion_at = now
            log_entry = PartnerActivityLog(
                partner_id=partner.id,
                event_type="loss_aversion",
                icon="⚠️",
                title=f"Pending Vault Alert: ${pending_potential:.2f}/mo at risk",
                description=f"Loss aversion reminder dispatched with fresh viral hook.",
                potential_usd=pending_potential,
                email_sent=True,
                created_at=now,
            )
            db.session.add(log_entry)

            self._send_email_async(partner.user.email, subject, body_text, body_html)
            sent_count += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("[PARTNER AUTOMATION] Failed to commit loss aversion alerts: %s", e)

        return sent_count

    # ─────────────────────────────────────────────────────────────────────────
    # 5. TRIGGER: STATUS UPDATE & NEXT-TIER GRAVITY NUDGE
    # ─────────────────────────────────────────────────────────────────────────
    def check_and_send_tier_nudges(self, max_gap: int = 3, min_cooldown_days: int = 6) -> int:
        """
        Identifies partners close to unlocking the next reward tier (e.g., 2 away from Silver 30% cut).
        Sends gamified goal-gradient motivation email.
        """
        from models.user import db, Partner, PartnerActivityLog
        from routes.partners import calculate_partner_tier

        now = datetime.utcnow()
        cutoff_cooldown = now - timedelta(days=min_cooldown_days)

        active_partners = Partner.query.filter_by(is_active=True).all()
        sent_count = 0

        for partner in active_partners:
            tier_info = calculate_partner_tier(partner.total_conversions)
            next_tier = tier_info.get("next_tier_name")
            needed = tier_info.get("needed_subs", 999)

            if not next_tier or needed > max_gap or needed <= 0:
                continue

            if partner.last_tier_nudge_at and partner.last_tier_nudge_at > cutoff_cooldown:
                continue

            if not partner.user or not partner.user.email:
                continue

            subject = f"⚡ You are only {needed} Paid Subs away from {next_tier} ({tier_info['next_cut_pct']}% Cut)!"
            dashboard_url = f"{self.app_base_url}/partners/"

            body_text = (
                f"⚡ Next-Tier Proximity Alert!\n\n"
                f"You are currently at {tier_info['current_subs']} Paid Subs in the {tier_info['tier_name']} ({tier_info['cut_pct']}% Cut).\n\n"
                f"You are only {needed} Paid Subs away from unlocking {next_tier} ({tier_info['next_cut_pct']}% Cut + {tier_info['next_perks']})!\n\n"
                f"Top earners in {next_tier} are averaging $450/month in compounding recurring revenue.\n"
                f"You can easily hit this milestone before the weekend!\n\n"
                f"👉 Open your dashboard & grab this week's viral TikTok script:\n"
                f"{dashboard_url}\n"
            )
            body_html = self._render_template_html(
                badge="⚡ NEXT-TIER GRAVITY BOOST",
                title=f"Only {needed} Subs to {next_tier}!",
                highlight=f"{tier_info['current_subs']} / {tier_info['target_subs']} Progress ({tier_info['progress_pct']}%)",
                description=(
                    f"You are within striking distance of the <strong>{next_tier}</strong> echelon! "
                    f"Hitting this tier instantly elevates your lifetime cut to <strong>{tier_info['next_cut_pct']}% MRR</strong>. "
                    "Top creators in this bracket average $450/month in automated payouts."
                ),
                metrics=[
                    ("Current Tier", tier_info["tier_name"]),
                    ("Next Tier Cut", f"{tier_info['next_cut_pct']}% Lifetime"),
                    ("Subs Needed", str(needed)),
                ],
                action_text=f"Unlock {next_tier} Now →",
                action_url=dashboard_url,
            )

            partner.last_tier_nudge_at = now
            log_entry = PartnerActivityLog(
                partner_id=partner.id,
                event_type="tier_nudge",
                icon="⚡",
                title=f"Tier Alert: {needed} subs to {next_tier} ({tier_info['next_cut_pct']}%)",
                description=f"Status update dispatched: {tier_info['current_subs']}/{tier_info['target_subs']} paid subs.",
                potential_usd=0.0,
                email_sent=True,
                created_at=now,
            )
            db.session.add(log_entry)

            self._send_email_async(partner.user.email, subject, body_text, body_html)
            sent_count += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("[PARTNER AUTOMATION] Failed to commit tier nudges: %s", e)

        return sent_count

    # ─────────────────────────────────────────────────────────────────────────
    # 6. TRIGGER: CONVERSION PAID CHA-CHING NOTIFICATION
    # ─────────────────────────────────────────────────────────────────────────
    def on_conversion_paid(self, referral_code: str, new_user_id: int, amount_usd: float, plan_name: str = "starter"):
        """Fires when a referred user successfully buys a paid plan."""
        from models.user import db, Partner, PartnerActivityLog

        if not referral_code:
            return

        partner = Partner.query.filter_by(referral_code=referral_code.upper(), is_active=True).first()
        if not partner:
            return

        now = datetime.utcnow()
        log_entry = PartnerActivityLog(
            partner_id=partner.id,
            event_type="conversion",
            icon="💸",
            title=f"Paid Conversion! +${amount_usd:.2f}",
            description=f"User upgraded to {plan_name.title()}! Deposited directly into Settled Wallet.",
            potential_usd=amount_usd,
            email_sent=False,
            created_at=now,
        )
        db.session.add(log_entry)

        if partner.user and partner.user.email:
            subject = f"💸 Cha-Ching! +${amount_usd:.2f} Added to Your Wallet!"
            dashboard_url = f"{self.app_base_url}/partners/"
            log_entry.email_sent = True

            body_text = (
                f"💸 Cha-Ching! You just earned +${amount_usd:.2f}!\n\n"
                f"One of your referred users just upgraded to the {plan_name.title()} plan.\n"
                f"We've deposited the earnings directly into your Settled Wallet.\n\n"
                f"💰 Total Wallet Balance: ${partner.wallet_usd:.2f}\n"
                f"📈 Total Earned: ${partner.total_earned_usd:.2f}\n\n"
                f"👉 View your Settled Wallet & Payout details:\n"
                f"{dashboard_url}\n"
            )
            body_html = self._render_template_html(
                badge="💸 INSTANT CASH DEPOSIT",
                title="Cha-Ching! Conversion Cleared",
                highlight=f"+${amount_usd:.2f} Settled Cash",
                description=(
                    f"A referred creator upgraded to the <strong>{plan_name.title()}</strong> plan! "
                    f"We've credited <strong>+${amount_usd:.2f}</strong> straight to your Settled Wallet. "
                    "Your recurring annuity is compounding."
                ),
                metrics=[
                    ("Settled Wallet", f"${partner.wallet_usd:.2f}"),
                    ("Total Earned", f"${partner.total_earned_usd:.2f}"),
                    ("Paid Conversions", str(partner.total_conversions)),
                ],
                action_text="View Your Settled Wallet →",
                action_url=dashboard_url,
            )
            self._send_email_async(partner.user.email, subject, body_text, body_html)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("[PARTNER AUTOMATION] Failed to commit conversion activity: %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    # 7. BEAUTIFUL DARK-MODE EMAIL TEMPLATE RENDERER
    # ─────────────────────────────────────────────────────────────────────────
    def _render_template_html(
        self,
        badge: str,
        title: str,
        highlight: str,
        description: str,
        metrics: list,
        action_text: str,
        action_url: str,
        fresh_hook: str = None,
    ) -> str:
        metrics_html = "".join([
            f"""
            <td style="padding:14px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,200,80,0.18);border-radius:12px;text-align:center;width:33%;">
              <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:600;">{lbl}</div>
              <div style="font-size:18px;font-weight:800;color:#FFD580;">{val}</div>
            </td>
            """ for lbl, val in metrics
        ])

        hook_html = ""
        if fresh_hook:
            hook_html = f"""
            <div style="margin:20px 0;padding:16px 20px;background:linear-gradient(135deg,rgba(255,200,80,0.1) 0%,rgba(0,0,0,0.4) 100%);border-left:3px solid #FFD580;border-radius:8px;">
              <div style="font-size:11px;color:#FFD580;font-weight:800;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">🎣 Ready-To-Post Hook:</div>
              <div style="font-size:14px;color:#fff;font-style:italic;line-height:1.5;">"{fresh_hook}"</div>
            </div>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#07031a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#f0f0f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#07031a;padding:36px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:560px;background:linear-gradient(180deg,#140d33 0%,#0c0624 100%);border:1px solid rgba(255,200,80,0.25);border-radius:20px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.6);">
          
          <!-- Header -->
          <tr>
            <td style="padding:28px 32px 20px;border-bottom:1px solid rgba(255,255,255,0.06);text-align:center;">
              <span style="display:inline-block;padding:4px 12px;background:rgba(255,200,80,0.12);color:#FFD580;border:1px solid rgba(255,200,80,0.3);border-radius:20px;font-size:11px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;margin-bottom:12px;">{badge}</span>
              <h1 style="margin:0;font-size:22px;font-weight:900;color:#ffffff;line-height:1.3;">{title}</h1>
            </td>
          </tr>

          <!-- Highlight Banner -->
          <tr>
            <td style="padding:24px 32px 0;text-align:center;">
              <div style="display:inline-block;padding:12px 24px;background:radial-gradient(circle,rgba(255,180,60,0.18) 0%,rgba(0,0,0,0) 80%);border:1.5px solid rgba(255,190,60,0.5);border-radius:16px;">
                <span style="font-size:26px;font-weight:900;color:#FFD580;letter-spacing:-0.5px;">{highlight}</span>
              </div>
            </td>
          </tr>

          <!-- Body Description -->
          <tr>
            <td style="padding:20px 32px;font-size:14px;color:#cccccc;line-height:1.6;text-align:center;">
              {description}
            </td>
          </tr>

          <!-- Hook block if present -->
          {f"<tr><td style='padding:0 32px;'>{hook_html}</td></tr>" if fresh_hook else ""}

          <!-- Metric Cards -->
          <tr>
            <td style="padding:10px 32px 24px;">
              <table role="presentation" width="100%" cellspacing="8" cellpadding="0">
                <tr>
                  {metrics_html}
                </tr>
              </table>
            </td>
          </tr>

          <!-- Action CTA -->
          <tr>
            <td style="padding:0 32px 36px;text-align:center;">
              <a href="{action_url}" target="_blank" style="display:inline-block;padding:14px 28px;background:linear-gradient(135deg,#FFD580 0%,#FFB347 100%);color:#07031a;text-decoration:none;font-size:14px;font-weight:900;border-radius:12px;box-shadow:0 6px 22px rgba(255,180,60,0.4);letter-spacing:0.3px;">
                {action_text}
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;background:rgba(0,0,0,0.3);border-top:1px solid rgba(255,255,255,0.05);text-align:center;font-size:11px;color:#666666;">
              HotShort Partner Growth Engine · Earn 30% Monthly Recurring Revenue for Life.<br>
              You received this because of your partner account on <a href="{self.app_base_url}" style="color:#888888;text-decoration:underline;">HotShort</a>.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


# Singleton Engine Instance
partner_automation = PartnerAutomationEngine()
