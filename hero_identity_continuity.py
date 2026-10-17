"""Private same-game hero proof; never caches offers or grants capture.

The caller supplies a freshly verified game process scope and current card-scene
proof. Supported transient portrait abstentions can borrow an established own
identity. This is continuity, not a new portrait recognition or mode detector.
The lifetime is the caller's exact verified game scope, not an elapsed-time
guess about respawn duration. Current display still requires a fresh capture.
"""
import math


def _time(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


class HeroIdentityContinuity:
    def __init__(self):self.clear()

    def clear(self):
        self.scope=None;self.hero='';self.champion_id='';self.frames=0
        self.last_frame=None;self.last_serial=None;self.verified_at=None
        self.last_recovery_frame=None;self.last_recovery_serial=None

    def _revoke_identity(self):
        # Keep the current scope's replay watermarks. An older result must not
        # resurrect an identity revoked by a newer conflicting observation.
        self.hero='';self.champion_id='';self.frames=0;self.verified_at=None

    @staticmethod
    def _fresh(scope,captured_at,now):
        return bool(scope and _time(now) and _time(captured_at)
            and 0<=now-captured_at<=4)

    @staticmethod
    def _serial(serial):return type(serial) is int and serial>0

    def _new_frame(self,captured_at,serial):
        return (self._serial(serial)
            and (self.last_frame is None or captured_at>self.last_frame)
            and (self.last_serial is None or serial>self.last_serial))

    def _current_identity(self,now):
        return (self.verified_at is not None and _time(now)
            and now>=self.verified_at)

    @staticmethod
    def supported_abstention(observation):
        # API false means an explicit conflict/untrusted identity. Network/API
        # unavailability instead falls back to the ordinary HUD observation.
        return (isinstance(observation,dict)
            and observation.get('confident') is False
            and observation.get('method')=='own-hud-portrait'
            and observation.get('abstentionKind')!='unsupported-layout'
            and observation.get('conflict') is not True
            and (observation.get('abstentionKind')=='portrait-unavailable'
                or observation.get('occlusionKind')=='death-portrait'))

    @staticmethod
    def _strong_identity(observation):
        if (not isinstance(observation,dict) or observation.get('confident') is not True
                or observation.get('method') not in ('own-hud-portrait','game-client-api')
                or observation.get('conflict') is True
                or observation.get('abstentionKind')=='unsupported-layout'):
            return None
        hero=observation.get('hero');cid=observation.get('championId')
        if (not isinstance(hero,str) or not hero.strip() or not isinstance(cid,str)
                or not 1<=len(cid)<=6 or not cid.isascii() or not cid.isdecimal() or cid[0]=='0'):
            return None
        return hero,cid

    def observe(self,observation,*,scope,captured_at,now,serial):
        if not self._fresh(scope,captured_at,now) or not self._serial(serial):
            if scope==self.scope:self._revoke_identity()
            else:self.clear()
            return False
        if scope!=self.scope:self.clear();self.scope=scope
        if not self._new_frame(captured_at,serial):return False
        previous_frame=self.last_frame
        self.last_frame=captured_at;self.last_serial=serial
        if self.verified_at is not None and not self._current_identity(now):self._revoke_identity()
        strong=self._strong_identity(observation)
        if strong is None:
            if not self.supported_abstention(observation) or self.verified_at is None:
                self._revoke_identity()
            return False
        hero,cid=strong
        same=hero==self.hero and cid==self.champion_id
        if self.verified_at is not None and not same:
            self._revoke_identity();return False
        contiguous=previous_frame is not None and captured_at-previous_frame<=4
        self.frames=min(2,self.frames+1) if same and (contiguous or self.verified_at is not None) else 1
        self.hero=hero;self.champion_id=cid
        self.verified_at=captured_at if self.frames>=2 else None
        return self.verified_at is not None

    def eligible(self,observation,*,scope,captured_at,now,serial=None):
        """Nonmutating early-proof check; neither confirms nor renews identity."""
        return bool(scope==self.scope and self._fresh(scope,captured_at,now)
            and self._current_identity(now) and self.supported_abstention(observation)
            and (self.last_frame is None or captured_at>self.last_frame)
            and (serial is None or self._new_frame(captured_at,serial)))

    def recover(self,observation,*,scope,captured_at,now,fresh_card_scene,ocr_reused=False,serial=None):
        """Call before observe() for the final capture; do not rewrite raw proof.

        Only observe() advances the observation watermark. A separate recovery
        watermark prevents the same result from displaying twice even if its
        caller has not yet recorded the corresponding final observation.
        """
        if (scope!=self.scope or not self._fresh(scope,captured_at,now)
                or not self._current_identity(now)):
            if scope==self.scope:self._revoke_identity()
            else:self.clear()
            return None
        if not self._new_frame(captured_at,serial):return None
        if (self.last_recovery_frame is not None and captured_at<=self.last_recovery_frame
                or self.last_recovery_serial is not None and serial<=self.last_recovery_serial):return None
        if not self.supported_abstention(observation):
            self._revoke_identity();return None
        if fresh_card_scene is not True or ocr_reused is not False:return None
        self.last_recovery_frame=captured_at;self.last_recovery_serial=serial
        return {'hero':self.hero,'championId':self.champion_id,
            'method':'same-game-hero-continuity','reason':'沿用本局此前确认的英雄；当前头像暂未重新确认'}
