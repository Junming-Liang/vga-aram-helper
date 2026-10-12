"""Session-scoped client→game identity evidence; stores no pictures/nicknames.

Caller must validate screenshot scene and window permission before calling.
The state explicitly distinguishes current assignment, carried provisional
identity, and independently HUD-verified identity. Countdown is never a lock.
"""
from dataclasses import dataclass
import math


def valid_time(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def identity(value):
    if not isinstance(value,(tuple,list)) or len(value)!=3:raise ValueError('Expected permitted HWND/PID/class identity')
    hwnd,pid,cls=value
    if not isinstance(hwnd,int) or isinstance(hwnd,bool) or hwnd<=0 or not isinstance(pid,int) or isinstance(pid,bool) or pid<=0 or not isinstance(cls,str) or not cls:raise ValueError('Invalid window identity')
    return (hwnd,pid,cls)


@dataclass
class SelectionSession:
    active:bool=False
    client:tuple|None=None
    game:tuple|None=None
    generation:int=0
    stage:str='idle'
    candidate:str=''
    candidate_frames:int=0
    assigned:str=''
    carried:str=''
    verified:str=''
    last_client_frame:float=0.
    transition_at:float=0.
    last_game_frame:float=0.
    reason:str='Not started'
    last_event_frame:float=0.

    def clear(self,reason, *, stage='waiting'):
        self.generation+=1;self.stage=stage;self.candidate='';self.candidate_frames=0
        self.assigned='';self.carried='';self.verified='';self.last_client_frame=0.;self.transition_at=0.;self.last_game_frame=0.;self.reason=reason
    def start(self,client_identity):
        self.client=identity(client_identity);self.game=None;self.active=True;self.last_event_frame=0.;self.clear('Explicit session capture started');return self.generation
    def stop(self):
        self.clear('Capture stopped',stage='idle');self.active=False;self.client=None;self.game=None
    def _fresh(self,captured_at,now):return valid_time(captured_at) and valid_time(now) and 0<=now-captured_at<=4
    def observe_client(self,observation,window,captured_at,now, *, generation):
        if not self.active or generation!=self.generation:return False
        if identity(window)!=self.client:
            self.clear('Unpermitted/different client identity');return False
        if not self._fresh(captured_at,now):self.clear('Client observation expired');return False
        if captured_at<=self.last_event_frame:return False
        if self.last_client_frame and captured_at-self.last_client_frame>4:self.clear('Client observation gap resets assignment stability')
        self.last_event_frame=captured_at
        scene=observation.get('scene') if isinstance(observation,dict) else None
        if scene!='assigned-selection' or observation.get('assigned') is not True:
            self.clear('No unambiguous current own assignment',stage='unassigned' if scene in ('initial-cards','new-selection') else 'waiting');self.game=None;return False
        champion=observation.get('championId')
        if not isinstance(champion,str) or not champion.isdecimal():self.clear('Invalid canonical champion');return False
        # Returning from game/transition to client select always starts fresh.
        if self.stage in ('transition','game-provisional','game-verified'):
            self.clear('A new selection scene replaces previous match');self.game=None
        if champion!=self.candidate:
            self.clear('Own assignment changed; awaiting a second observation',stage='assigning');self.candidate=champion;self.candidate_frames=1
        else:self.candidate_frames+=1
        self.last_client_frame=captured_at
        if self.candidate_frames>=2:
            self.assigned=champion;self.stage='assigned';self.reason='Stable current assignment, not an irrevocable lock';return True
        return False
    def begin_handoff(self,game_identity,now, *, generation,new_game_window=False):
        """Only an observed new-game-window handoff within4s of client evidence can carry.

        Calling this never authorizes a window: caller must apply the explicit
        client+game capture permission and unique-window checks first.
        """
        if not self.active or generation!=self.generation:return False
        if not new_game_window or not valid_time(now) or self.stage!='assigned' or not self.assigned or not 0<=now-self.last_client_frame<=4:
            self.clear('Selection-to-loading continuity not established');return False
        self.generation+=1;self.game=identity(game_identity);self.carried=self.assigned;self.verified='';self.stage='transition';self.transition_at=now;self.reason='Provisional identity from this selection; HUD unverified';return True
    def observe_game(self,window,captured_at,now, *, generation,game_scene=False,hud_hero=None,match_ended=False):
        if not self.active or generation!=self.generation:return False
        if self.game is None or identity(window)!=self.game:
            self.clear('Unpermitted/different game identity');return False
        if match_ended or not game_scene:
            self.clear('Game scene ended or cannot be established');self.game=None;return False
        if not self._fresh(captured_at,now):self.clear('Game observation expired');return False
        if captured_at<=self.last_event_frame:return False
        if self.stage in ('game-provisional','game-verified') and self.last_game_frame and captured_at-self.last_game_frame>4:
            self.clear('Game observation continuity lost');return False
        self.last_event_frame=captured_at
        if self.stage=='transition' and now-self.transition_at>120:
            self.clear('Loading continuity expired');return False
        if not self.carried:
            self.clear('No valid selection identity to carry');return False
        self.last_game_frame=captured_at
        if hud_hero is not None:
            if str(hud_hero)!=self.carried:
                self.clear('HUD contradicts carried selection; old tiers must hide');return False
            self.verified=self.carried;self.stage='game-verified';self.reason='This-session selection independently verified by own HUD';return True
        # This is provenance, NOT a claim that an unknown portrait was recognized.
        self.stage='game-provisional';self.reason='From this session champion select; own HUD still unverified';return True
    def expire(self,now):
        if not valid_time(now):self.clear('Invalid clock');return
        if self.stage in ('assigned','assigning') and now-self.last_client_frame>4:self.clear('No fresh client observation')
        elif self.stage=='transition' and now-self.transition_at>120:self.clear('Loading timeout')
        elif self.stage in ('game-provisional','game-verified') and now-self.last_game_frame>4:self.clear('No fresh game observation')
    def visible_identity(self, *, allow_provisional=False):
        if self.stage=='game-verified':return {'championId':self.verified,'source':'client-text+own-hud','verified':True}
        if allow_provisional and self.stage=='game-provisional':return {'championId':self.carried,'source':'this-session-client-text','verified':False,'warning':'HUD未复核'}
        return None
