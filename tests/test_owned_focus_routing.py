"""Portable exact-owned focus contracts; native activation remains a Windows gate."""
import ast
import copy
import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import windows_selection_smoke as shared
import windows_automatic_capture as automatic
import selection_smoke as diagnostic
from test_windows_automatic_capture import good_focus_transitions
from test_windows_selection_smoke import good_owned_focus


class OwnedFocusRoutingTests(unittest.TestCase):
    def owners(self):
        return [dict(process={'pid':pid},exe=Path(role+'.exe'),window={'hwnd':hwnd,'pid':pid},
                     size=(964,602),role=role,created=created)
                for role,hwnd,pid,created in (('client',100,101,200),('game',500,501,100))]

    def native(self,foreground,*,result=1,sent=True,api=True,drain=True):
        calls=[];current=[foreground]
        def send(hwnd,message,wparam,lparam,flags,timeout,response):
            calls.append((hwnd,message,wparam,lparam,flags,timeout))
            if message==0:
                if drain:current[0]=hwnd
                return drain
            ctypes.cast(response,ctypes.POINTER(ctypes.c_size_t)).contents.value=result
            if result==1:current[0]=wparam
            return sent
        def activate(hwnd):
            calls.append(('activate',hwnd))
            if api and result==1:current[0]=hwnd
            return api
        def pid(hwnd,pointer):
            ctypes.cast(pointer,ctypes.POINTER(shared.W.DWORD)).contents.value=os.getpid();return 1
        native=SimpleNamespace(u=SimpleNamespace(GetForegroundWindow=lambda:current[0],
            SendMessageTimeoutW=Mock(side_effect=send),SetForegroundWindow=Mock(side_effect=activate),
            GetWindowThreadProcessId=Mock(side_effect=pid)),image=Mock(return_value='own-python'))
        return native,current,calls

    def creation(self,native,process):
        return {101:200,501:100}.get(process.get('pid'),300)

    def test_pair_is_bidirectional_and_creation_order_is_not_focus_authority(self):
        for source_index in (0,1):
            source,target=self.owners()[source_index],self.owners()[1-source_index]
            native,_,calls=self.native(source['window']['hwnd']);receipt={}
            with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=self.creation):
                shared.focus_owned_target(native,target,[source],receipt)
            shared.validate_owned_focus(receipt,target_role=target['role'])
            self.assertEqual(calls[0][1],shared.WM_FOCUS_OWNED_GAME if target['role']=='game' else shared.WM_FOCUS_OWNED_PAIR_CLIENT)
            native.u.SetForegroundWindow.assert_not_called()
        # Selection's separate new-game lifetime cutoff stays restrictive.
        source,target=self.owners()
        with self.assertRaises(AssertionError):
            shared.focus_owned_game(native,source['process'],source['exe'],source['window'],source['size'],
                target['process'],target['exe'],target['window'],target['size'],200,{'created':100})

    def test_dispatch_already_and_unknown_never_request_activation(self):
        for foreground in (100,999,0):
            native,_,calls=self.native(foreground);receipt={}
            with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=self.creation):
                if foreground==100:
                    shared.focus_owned_target(native,self.owners()[0],self.owners(),receipt)
                    shared.validate_owned_focus(receipt)
                else:
                    with self.assertRaisesRegex(AssertionError,'no known foreground owner'):
                        shared.focus_owned_target(native,self.owners()[0],self.owners(),receipt)
                    self.assertEqual(receipt['focus']['before'],0)
            self.assertEqual(calls,[])

    def test_controller_actual_owner_success_pending_denial_and_one_shot(self):
        controller=dict(hwnd=600,pid=os.getpid(),created=300,image='own-python')
        for api,result,drain,passed in ((True,1,False,True),(True,3,True,True),
                                      (True,3,False,False),(False,1,True,False)):
            with self.subTest(api=api,result=result,drain=drain):
                native,current,calls=self.native(600,result=result,api=api,drain=drain);receipt={}
                with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=self.creation):
                    if passed:shared.focus_owned_target(native,self.owners()[0],[],receipt,controller=controller)
                    else:
                        with self.assertRaisesRegex(AssertionError,'controller focus request failed'):
                            shared.focus_owned_target(native,self.owners()[0],[],receipt,controller=controller)
                    self.assertEqual(native.u.SetForegroundWindow.call_count,1)
                    self.assertEqual(native.u.SendMessageTimeoutW.call_count,1 if api and result==3 else 0)
                    saved=copy.deepcopy(receipt);current[0]=100
                    with self.assertRaisesRegex(AssertionError,'must not be retried'):
                        shared.focus_owned_target(native,self.owners()[0],[],receipt,controller=controller)
                    self.assertEqual(receipt,saved)
                if passed:shared.validate_owned_focus(receipt)

    def test_controller_identity_or_focus_loss_rejects_before_request(self):
        for change in ('pid','created','image','foreground'):
            native,_,_=self.native(600);controller=dict(hwnd=600,pid=os.getpid(),created=300,image='own-python')
            if change=='pid':controller['pid']+=1
            elif change=='created':controller['created']+=1
            elif change=='image':controller['image']='other'
            else:native.u.GetForegroundWindow=Mock(side_effect=[600,999])
            with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=self.creation):
                with self.assertRaises(AssertionError):shared.focus_owned_target(native,self.owners()[0],[],{},controller=controller)
            native.u.SetForegroundWindow.assert_not_called();native.u.SendMessageTimeoutW.assert_not_called()

    def test_receipt_validator_rejects_typed_forgery_and_wrong_roles(self):
        for route in ('already','pair','controller'):
            value=good_owned_focus(route=route,source_role='controller' if route=='controller' else None)
            shared.validate_owned_focus(value)
            mutations=[('route','unknown'),('target',{}),('focus',{}),('target.pid',True),
                ('target.created',0),('focus.after',999),('focus.sent',1),('focus.result',True),('focus.drained',1)]
            if route!='already':mutations += [('source.pid',101),('source.role','client'),('focus.api',1),('focus.before',100)]
            for field,replacement in mutations:
                changed=copy.deepcopy(value);parts=field.split('.');where=changed
                for part in parts[:-1]:where=where[part]
                where[parts[-1]]=replacement
                with self.subTest(route=route,field=field),self.assertRaises(AssertionError):shared.validate_owned_focus(changed)

    def test_all_automatic_calls_have_ordered_receipts_and_no_observer_retry(self):
        source=Path(automatic.__file__).read_text();tree=ast.parse(source)
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
               and node.func.id=='foreground']
        phases=[call.args[1].value for call in sorted(calls,key=lambda c:c.lineno)]
        self.assertEqual(phases,[p for p,_ in automatic.FOCUS_PHASES])
        self.assertNotIn('foreground_owned',source)
        for operation in ('game minimize','game recreation','game close'):
            call=next(c for c in calls if c.args[1].value=='prepare client before '+operation)
            self.assertEqual([(k.arg,k.value.value) for k in call.keywords],[('settle',False)])
        before=source.index("foreground(client,'prepare client before game minimize',settle=False)")
        minimize=source.index('native.u.ShowWindow(game[',before)
        between=source[before:minimize]
        self.assertIn('control.state.confirmed',between);self.assertIn('control.overlay.isVisible()',between)
        self.assertIn('minimized_game_target.identity',between);self.assertNotIn('events.',between)
        self.assertIn('assert_minimized_target_rejected(control.capture, minimized_game_target)',source)
        receipts=good_focus_transitions();automatic.validate_focus_transitions(receipts)
        for changed in (receipts[:-1],receipts[::-1],receipts+[receipts[0]]):
            with self.assertRaises(AssertionError):automatic.validate_focus_transitions(changed)
        for index in (4,5,6,8,11,12,13):
            changed=copy.deepcopy(receipts);changed[index]['target']['created']+=1
            with self.subTest(lifetime=index),self.assertRaises(AssertionError):automatic.validate_focus_transitions(changed)
        for index in range(len(receipts)):
            changed=copy.deepcopy(receipts);changed[index]['focus']['after']=0
            with self.subTest(index=index),self.assertRaises(AssertionError):automatic.validate_focus_transitions(changed)

    def test_actual_nested_automatic_dispatcher_executes_every_callsite_in_order(self):
        tree=ast.parse(Path(automatic.__file__).read_text())
        helper=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='foreground')
        calls=sorted([n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                      and n.func.id=='foreground'],key=lambda n:n.lineno)
        native,current,actions=self.native(600);native.poll=lambda process:None
        client,game=self.owners();owned=[client,game];events=SimpleNamespace(settle=Mock())
        namespace=dict(automatic.__dict__,native=native,result={'focus_transitions':[]},owned=owned,
            normalized_path=str,allowed={'client.exe','game.exe'},control=SimpleNamespace(winId=lambda:600),
            controller_metadata=SimpleNamespace(created=300),controller_image='own-python',events=events,
            client=client,game=game)
        exec(compile(ast.Module(body=[helper],type_ignores=[]),'actual-automatic-focus-helper','exec'),namespace)
        def creation(native,process):
            return next((item['created'] for item in owned if item['process']['pid']==process.get('pid')),300)
        with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=creation):
            for index,call in enumerate(calls):
                if index==8:game['window']={'hwnd':550,'pid':501}
                if index==11:
                    game=copy.deepcopy(game);game.update(process={'pid':701},window={'hwnd':700,'pid':701},created=400)
                    owned.append(game);namespace['game']=game
                if index==12:current[0]=600
                previous=events.settle.call_count
                exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(call)],type_ignores=[])),
                             'actual-automatic-focus-call','exec'),namespace)
                self.assertEqual(current[0],namespace[call.args[0].id]['window']['hwnd'])
                self.assertEqual(events.settle.call_count-previous,0 if index in (2,7,9) else 1)
        receipts=namespace['result']['focus_transitions'];automatic.validate_focus_transitions(receipts)
        self.assertEqual([r['route'] for r in receipts],
            ['controller','pair','pair','already','pair','already','already','pair','pair','pair','already','pair','controller','already'])
        self.assertEqual(sum(r['focus']['sent'] for r in receipts),9)

    def test_actual_selection_final_game_call_uses_already_or_exact_client_once(self):
        tree=ast.parse(Path(shared.__file__).read_text())
        call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                  and n.func.id=='focus_owned_target' and isinstance(n.args[1],ast.Name) and n.args[1].id=='game_owner')
        client,game=self.owners()
        for before,route in ((500,'already'),(100,'pair'),(999,None)):
            native,current,_=self.native(before);namespace=dict(shared.__dict__,native=native,
                game_owner=game,client_owner=client,result={})
            with patch.object(shared,'assert_owned_window'),patch.object(shared,'owned_process_created',side_effect=self.creation):
                compiled=compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(call)],type_ignores=[])),
                                 'actual-selection-final-focus','exec')
                if route is None:
                    with self.assertRaises(AssertionError):exec(compiled,namespace)
                    self.assertEqual(native.u.SendMessageTimeoutW.call_count,0)
                else:
                    exec(compiled,namespace);self.assertEqual(namespace['result']['final_game_focus']['route'],route)
                    shared.validate_owned_focus(namespace['result']['final_game_focus'],target_role='game')
                    self.assertEqual(current[0],500)
                    self.assertEqual(native.u.SendMessageTimeoutW.call_count,int(route=='pair'))

    def test_initial_helper_actual_qt_window_records_denied_and_async_focus_before_hide(self):
        from PySide6.QtWidgets import QApplication,QWidget
        from session_windows import ProcessMetadata
        app=QApplication.instance()or QApplication([])
        widget=QWidget();widget.show();app.processEvents();source=int(widget.winId())
        own=ProcessMetadata('own-python',300);client=ProcessMetadata('client.exe',200)
        target=SimpleNamespace(hwnd=100,pid=101,identity=('client',100))
        for api,result,drain,passed in ((True,1,False,True),(True,3,True,True),(True,3,False,False),(False,1,True,False)):
            native,_,_=self.native(source,api=api,result=result,drain=drain);receipt={}
            control=SimpleNamespace(winId=widget.winId,capture=SimpleNamespace(u=native.u,
                info=lambda hwnd:target if hwnd==100 else SimpleNamespace(pid=os.getpid())),
                window_policy=SimpleNamespace(permits=lambda value:True))
            with patch('session_windows.process_metadata',side_effect=lambda pid:own if pid==os.getpid() else client):
                if passed:diagnostic.focus_client_before_hiding_control(control,target,own,client,receipt)
                else:
                    with self.assertRaises(AssertionError):diagnostic.focus_client_before_hiding_control(control,target,own,client,receipt)
            self.assertEqual(receipt['api'],api);self.assertTrue(widget.isVisible())
            self.assertEqual(native.u.SetForegroundWindow.call_count,1)
            self.assertEqual(native.u.SendMessageTimeoutW.call_count,1 if api and result==3 else 0)
            if passed:shared.validate_initial_focus(receipt,100)
        widget.close()
