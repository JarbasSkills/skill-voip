import time
from itertools import chain
from time import sleep

from baresipy import BareSIP
from baresipy.contacts import ContactList
from ovos_bus_client.message import Message
from ovos_utils.file_utils import read_vocab_file
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills.fallback import FallbackSkill


class SIPSkill(FallbackSkill):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # skill settings defaults
        if "intercept_allowed" not in self.settings:
            self.settings["intercept_allowed"] = True
        if "confirm_operations" not in self.settings:
            self.settings["confirm_operations"] = True
        if "debug" not in self.settings:
            self.settings["debug"] = True
        if "priority" not in self.settings:
            self.settings["priority"] = 50
        if "timeout" not in self.settings:
            self.settings["timeout"] = 15

        # auto answer incoming calls
        if "auto_answer" not in self.settings:
            self.settings["auto_answer"] = False
        if "auto_reject" not in self.settings:
            self.settings["auto_reject"] = False
        if "auto_speech" not in self.settings:
            self.settings["auto_speech"] = "I am busy, try again later"

        # sip creds
        if "user" not in self.settings:
            self.settings["user"] = None
        if "gateway" not in self.settings:
            self.settings["gateway"] = None
        if "password" not in self.settings:
            self.settings["password"] = None

        # events
        self.settings_change_callback = self.on_voip_settings_change

        # state trackers
        self.on_hold = False
        self.muted = False
        self.intercepting_utterances = False
        self._old_settings = dict(self.settings)

        self.sip = None
        self.say_vocab = None
        self.cb = None
        self.contacts = ContactList("mycroft_sip")

    def initialize(self):
        self.register_fallback(self.handle_fallback, int(self.settings["priority"]))

        say_voc = self.find_resource('and_say.voc', 'vocab')
        if say_voc:
            # load vocab and flatten into a simple list
            # TODO sort by length
            self.say_vocab = list(chain(*read_vocab_file(say_voc)))
        self.start_sip()

        # Register GUI Events
        self.handle_gui_state("Clear")
        self.gui.register_handler("voip.jarbas.acceptCall", self.accept_call)
        self.gui.register_handler("voip.jarbas.hangCall", self.hang_call)
        self.gui.register_handler("voip.jarbas.muteCall", self.mute_call)
        self.gui.register_handler("voip.jarbas.unmuteCall", self.unmute_call)
        self.gui.register_handler("voip.jarbas.callContact", self.handle_call_contact_from_gui)
        self.gui.register_handler("voip.jarbas.updateConfig", self.handle_config_from_gui)
        self.add_event('skill-voip.jarbasskills.home', self.show_homescreen)

    def on_voip_settings_change(self):
        if self.settings["auto_reject"]:
            self.settings["auto_answer"] = False
        elif self.settings["auto_answer"]:
            self.settings["auto_reject"] = False

            if self.settings["auto_speech"] != \
                    self._old_settings["auto_speech"]:
                self.speak_dialog("accept_all",
                                  {"speech": self.settings["auto_speech"]})

        if self.sip is None:
            if self.settings["gateway"]:
                self.start_sip()
            else:
                self.speak_dialog("credentials_missing")
        else:
            for k in ["user", "password", "gateway"]:
                if self.settings[k] != self._old_settings[k]:
                    self.speak_dialog("sip_restart")
                    self.sip.quit()
                    self.sip = None
                    self.intercepting_utterances = False  # just in case
                    self.start_sip()
                    break
        self._old_settings = dict(self.settings)

    def start_sip(self):
        if self.sip is not None:
            self.sip.quit()
            sleep(0.5)
        self.sip = BareSIP(self.settings["user"],
                           self.settings["password"],
                           self.settings["gateway"],
                           block=False,
                           debug=self.settings["debug"])
        self.sip.handle_incoming_call = self.handle_incoming_call
        self.sip.handle_call_ended = self.handle_call_ended
        self.sip.handle_login_failure = self.handle_login_failure
        self.sip.handle_login_success = self.handle_login_success
        self.sip.handle_call_established = self.handle_call_established

    # SIP
    def _wait_until_call_established(self):
        while not self.sip.call_established:
            sleep(0.5)  # TODO timeout in case of errors

    def accept_call(self):
        self.sip.accept_call()
        self.handle_gui_state("Connected")

    def hang_call(self):
        self.sip.hang()
        self.intercepting_utterances = False

    def mute_call(self):
        self.gui["call_muted"] = True
        self.sip.mute_mic()

    def unmute_call(self):
        self.gui["call_muted"] = False
        self.sip.unmute_mic()

    def add_new_contact(self, name, address, prompt=False):
        name = name.replace("_", " ").replace("-", " ").strip()
        address = address.strip()
        contact = self.contacts.get_contact(name)
        # new address
        if contact is None:
            self.log.info(f"Adding new contact {name}:{address}")
            self.contacts.add_contact(name, address)
            self.speak_dialog("contact_added", {"contact": name}, wait=True)
        # update contact (address exist)
        else:
            contact = self.contacts.search_contact(address) or contact
            if prompt and \
                    (name != contact["name"] or address != contact["url"]):
                if self.ask_yesno("update_confirm", data={"contact":
                                                              name}) == "no":
                    return
            self.log.info(f"Updating contact {name}:{address}")
            if name != contact["name"]:
                # new name (unique ID)
                self.contacts.remove_contact(contact["name"])
                self.contacts.add_contact(name, address)
                self.speak_dialog("contact_updated", {"contact": name},
                                  wait=True)
            elif address != contact["url"]:
                # new address
                self.contacts.update_contact(name, address)
                self.speak_dialog("contact_updated", {"contact": name},
                                  wait=True)

    def delete_contact(self, name, prompt=False):
        name = name.replace("_", " ").replace("-", " ").strip()
        if self.contacts.get_contact(name):
            if prompt:
                if self.ask_yesno("delete_confirm",
                                  data={"contact": name}) == "no":
                    return
            self.log.info(f"Deleting contact {name}")
            self.contacts.remove_contact(name)
            self.speak_dialog("contact_deleted", {"contact": name})

    def speak_and_hang(self, speech):
        self._wait_until_call_established()
        self.sip.mute_mic()
        self.sip.speak(speech)
        self.hang_call()

    def handle_call_established(self):
        self.handle_gui_state("Connected")
        if self.cb is not None:
            self.cb()
            self.cb = None

    def handle_login_success(self):
        pass
        # self.speak_dialog("sip_login_success")

    def handle_login_failure(self):
        self.log.error("Log in failed!")
        self.sip.quit()
        self.sip = None
        self.intercepting_utterances = False  # just in case
        if self.settings["user"] is not None and \
                self.settings["gateway"] is not None and \
                self.settings["password"] is not None:
            self.speak_dialog("sip_login_fail")
        else:
            self.speak_dialog("credentials_missing")

    def handle_incoming_call(self, number):
        if number.startswith("sip:"):
            number = number[4:]
        if self.settings["auto_answer"]:
            self.accept_call()
            self._wait_until_call_established()
            self.sip.speak(self.settings["auto_speech"])
            self.hang_call()
            self.log.info("Auto answered call")
            return
        if self.settings["auto_reject"]:
            self.log.info("Auto rejected call")
            self.hang_call()
            return
        contact = self.contacts.search_contact(number)
        if contact:
            self.gui["currentContact"] = contact["name"]
            self.handle_gui_state("Incoming")
            self.speak_dialog("incoming_call", {"contact": contact["name"]},
                              wait=True)
        else:
            self.gui["currentContact"] = "Unknown"
            self.handle_gui_state("Incoming")
            self.speak_dialog("incoming_call_unk", wait=True)
        self.intercepting_utterances = True

    def handle_call_ended(self, reason):
        self.handle_gui_state("Hang")
        self.log.info("Call ended")
        self.log.debug("Reason: " + reason)
        self.intercepting_utterances = False
        self.speak_dialog("call_ended", {"reason": reason})
        self.on_hold = False
        self.muted = False

    # intents
    def handle_utterance(self, utterance):
        # handle both fallback and converse stage utterances
        # control ongoing calls here
        if self.intercepting_utterances:
            if self.voc_match(utterance, 'reject'):
                self.hang_call()
                self.speak_dialog("call_rejected")
            elif self.muted or self.on_hold:
                # allow normal mycroft interaction in these cases only
                return False
            elif self.voc_match(utterance, 'accept'):
                speech = None
                if self.say_vocab and self.voc_match(utterance, 'and_say'):
                    for word in self.say_vocab:
                        if word in utterance:
                            speech = utterance.split(word)[1]
                            break
                # answer call
                self.accept_call()
                if speech:
                    self.speak_and_hang(speech)
                else:
                    # User 2 User
                    pass
            elif self.voc_match(utterance, 'hold_call'):
                self.on_hold = True
                self.sip.hold()
                self.speak_dialog("call_on_hold")
            elif self.voc_match(utterance, 'mute'):
                self.muted = True
                self.sip.mute_mic()
                self.speak_dialog("call_muted")
            # if in call always intercept utterance / assume false activation
            return True
        return False

    @intent_handler("restart.intent")
    def handle_restart(self, message):
        if self.sip is not None:
            self.sip.stop()
            self.sip = None
        self.handle_login(message)

    @intent_handler("login.intent")
    def handle_login(self, message):
        if self.sip is None:
            if self.settings["gateway"]:
                self.speak_dialog("sip_login",
                                  {"gateway": self.settings["gateway"]})
                self.start_sip()
            else:
                self.speak_dialog("credentials_missing")
        else:
            self.speak_dialog("sip_running")
            if self.ask_yesno("want_restart") == "yes":
                self.handle_restart(message)

    @intent_handler("call.intent")
    def handle_call_contact(self, message):
        name = message.data["contact"]
        self.log.debug("Placing call to " + name)
        contact = self.contacts.get_contact(name)
        if contact is not None:
            self.gui["currentContact"] = name
            self.speak_dialog("calling", {"contact": name}, wait=True)
            self.intercepting_utterances = True
            address = contact["url"]
            self.sip.call(address)
        else:
            self.speak_dialog("no_such_contact", {"contact": name})

    @intent_handler("call_and_say.intent")
    def handle_call_contact_and_say(self, message):
        utterance = message.data["speech"]

        def cb():
            self.speak_and_hang(utterance)

        self.cb = cb
        self.handle_call_contact(message)

    @intent_handler("resume_call.intent")
    @intent_handler("unmute.intent")
    def handle_resume(self, message):
        # TODO can both happen at same time ?
        if self.on_hold:
            self.on_hold = False
            self.speak_dialog("resume_call", wait=True)
            self.sip.resume()
        elif self.muted:
            self.muted = False
            self.speak_dialog("unmute_call", wait=True)
            self.sip.unmute_mic()
        else:
            self.speak_dialog("no_call")

    @intent_handler("reject_all.intent")
    def handle_auto_reject(self, message):
        self.settings["auto_reject"] = True
        self.settings["auto_answer"] = False
        self.speak_dialog("rejecting_all")

    @intent_handler("answer_all.intent")
    def handle_auto_answer(self, message):
        self.settings["auto_answer"] = True
        self.settings["auto_reject"] = False
        self.speak_dialog("accept_all",
                          {"speech": self.settings["auto_speech"]})

    @intent_handler("answer_all_and_say.intent")
    def handle_auto_answer_with(self, message):
        self.settings["auto_speech"] = message.data["speech"]
        self.handle_auto_answer(message)

    @intent_handler("contacts_list.intent")
    def handle_list_contacts(self, message):
        self.gui["contactListModel"] = self.contacts.list_contacts()
        self.handle_gui_state("Contacts")
        users = self.contacts.list_contacts()
        self.speak_dialog("contacts_list")
        for user in users:
            self.speak(user["name"])

    @intent_handler("contacts_number.intent")
    def handle_number_of_contacts(self, message):
        users = self.contacts.list_contacts()
        self.speak_dialog("contacts_number", {"number": len(users)})

    @intent_handler("disable_auto.intent")
    def handle_no_auto_answering(self, message):
        self.settings["auto_answer"] = False
        self.settings["auto_reject"] = False
        self.speak_dialog("no_auto")

    @intent_handler("call_status.intent")
    def handle_status(self, message):
        if self.sip is not None:
            self.speak_dialog("call_status", {"status": self.sip.call_status})
        else:
            self.speak_dialog("sip_not_running")

    # converse
    def handle_deactivate(self, message: Message):
        if self.settings["intercept_allowed"]:
            # avoid converse timed_out
            self.activate()

    def converse(self, utterances, lang="en-us"):
        if self.settings["intercept_allowed"] and utterances is not None:
            self.log.debug(f"{self.skill_id}: Intercept stage")
            return self.handle_utterance(utterances[0])
        return False

    # fallback
    def handle_fallback(self, message):
        utterance = message.data["utterance"]
        self.log.debug(f"{self.skill_id}: Fallback stage")
        return self.handle_utterance(utterance)

    # shutdown
    def shutdown(self):
        if self.sip is not None:
            self.sip.quit()

    # Handle GUI States Centrally
    def handle_gui_state(self, state):
        self.gui["call_muted"] = False
        if state == "Hang":
            self.gui["pageState"] = "Disconnected"
            self.gui.show_page("voipLoader.qml", override_idle=True)
            time.sleep(5)
            self.gui["currentContact"] = "Unknown"
            self.gui.clear()
            self.enclosure.display_manager.remove_active()
            self.bus.emit(Message("mycroft.mark2.reset_idle"))
        elif state == "Clear":
            self.gui["currentContact"] = "Unknown"
            self.gui.clear()
            self.enclosure.display_manager.remove_active()
            self.bus.emit(Message("mycroft.mark2.reset_idle"))
        else:
            self.gui["pageState"] = state
            self.gui.show_page("voipLoader.qml", override_idle=True)

    # Handle GUI Show Home
    @intent_handler("show_home.intent")
    def show_homescreen(self):
        self.handle_gui_state("Homescreen")

    # Handle Config From GUI
    def handle_config_from_gui(self, message):
        self.settings["user"] = message.data["username"]
        self.settings["gateway"] = message.data["gateway"]
        self.settings["password"] = message.data["password"]
        self.sip.quit()
        self.sip = None
        self.handle_restart({})

    # Handle Contact Calling From GUI
    def handle_call_contact_from_gui(self, message):
        if self.sip is not None:
            self.handle_gui_state("Outgoing")
            self.handle_call_contact(message)
        else:
            self.handle_call_failure_gui()

    # Handle Failure
    def handle_call_failure_gui(self):
        self.handle_gui_state("Failed")
        sleep(3)
        self.handle_gui_state("Clear")
