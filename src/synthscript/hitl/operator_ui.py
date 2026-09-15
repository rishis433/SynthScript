"""Simple terminal-based Operator UI for HITL sessions."""

import sys
from typing import Optional
from synthscript.hitl.manager import (
    SessionControlManager,
    InterventionContext,
    HumanAction,
    InterventionStatus,
)


class TerminalOperatorUI:
    """Simple terminal-based UI for human operators."""

    def __init__(self, manager: SessionControlManager):
        """Initialize the terminal operator UI.

        Args:
            manager: SessionControlManager instance
        """
        self.manager = manager

    def handle_intervention(self, context: InterventionContext) -> None:
        """Handle an intervention request.

        Args:
            context: Intervention context
        """
        session_id = self.manager.request_intervention(context)
        self.take_control(session_id)

    def take_control(self, session_id: str) -> None:
        """Take control of the session.

        Args:
            session_id: Session ID
        """
        self.manager.take_control(session_id)
        
        # Interactive loop for operator
        while True:
            try:
                self._show_menu()
                choice = input("\nEnter choice: ").strip()
                
                if choice == "1":
                    self._record_click()
                elif choice == "2":
                    self._record_type()
                elif choice == "3":
                    self._record_navigate()
                elif choice == "4":
                    self._show_status()
                elif choice == "5":
                    self._resume_automation(session_id)
                    break
                elif choice == "6":
                    self._abort_intervention(session_id)
                    break
                elif choice.lower() in ["q", "quit", "exit"]:
                    self._abort_intervention(session_id)
                    break
                else:
                    print("Invalid choice. Please try again.")
                    
            except KeyboardInterrupt:
                print("\n\nInterrupted by operator.")
                self._abort_intervention(session_id)
                break
            except Exception as e:
                print(f"Error: {e}")

    def _show_menu(self) -> None:
        """Show the operator menu."""
        print("\n" + "="*60)
        print("HITL OPERATOR MENU")
        print("="*60)
        print("1. Record Click Action")
        print("2. Record Type Action")
        print("3. Record Navigate Action")
        print("4. Show Session Status")
        print("5. Resume Automation")
        print("6. Abort Intervention")
        print("Q. Quit")
        print("="*60)

    def _record_click(self) -> None:
        """Record a click action."""
        element = input("Enter element description (e.g., 'Submit button'): ").strip()
        if not element:
            print("Action cancelled.")
            return
        
        action = HumanAction(
            action_type="CLICK",
            element_description=element,
        )
        self.manager.record_human_action(action)
        print(f"Recorded CLICK on '{element}'")

    def _record_type(self) -> None:
        """Record a type action."""
        element = input("Enter element description (e.g., 'Username field'): ").strip()
        if not element:
            print("Action cancelled.")
            return
        
        value = input("Enter value to type: ").strip()
        if not value:
            print("Action cancelled.")
            return
        
        action = HumanAction(
            action_type="TYPE",
            element_description=element,
            value=value,
        )
        self.manager.record_human_action(action)
        print(f"Recorded TYPE '{value}' in '{element}'")

    def _record_navigate(self) -> None:
        """Record a navigate action."""
        url = input("Enter URL to navigate to: ").strip()
        if not url:
            print("Action cancelled.")
            return
        
        action = HumanAction(
            action_type="NAVIGATE",
            value=url,
        )
        self.manager.record_human_action(action)
        print(f"Recorded NAVIGATE to '{url}'")

    def _show_status(self) -> None:
        """Show current session status."""
        session = self.manager.get_current_session()
        if not session:
            print("No active session.")
            return
        
        summary = self.manager.get_session_summary(session.session_id)
        if summary:
            print("\n" + "="*60)
            print("SESSION STATUS")
            print("="*60)
            print(f"Session ID: {summary['session_id']}")
            print(f"Status: {summary['status']}")
            print(f"Reason: {summary['reason']}")
            print(f"Message: {summary['message']}")
            print(f"Actions taken: {summary['human_actions_count']}")
            print(f"Resolution: {summary['resolution'] or 'In progress'}")
            print("="*60)

    def _resume_automation(self, session_id: str) -> None:
        """Resume automation."""
        confirm = input("Resume automation? (y/n): ").strip().lower()
        if confirm == "y":
            try:
                self.manager.resume_automation(session_id)
                print("Automation resumed successfully.")
            except Exception as e:
                print(f"Error resuming automation: {e}")
        else:
            print("Resume cancelled.")

    def _abort_intervention(self, session_id: str) -> None:
        """Abort the intervention."""
        confirm = input("Abort intervention? (y/n): ").strip().lower()
        if confirm == "y":
            try:
                self.manager.abort_intervention(session_id)
                print("Intervention aborted.")
            except Exception as e:
                print(f"Error aborting intervention: {e}")
        else:
            print("Abort cancelled.")


class SimpleOperatorUI:
    """Simplified non-interactive operator UI for testing."""

    def __init__(self, manager: SessionControlManager):
        """Initialize the simple operator UI.

        Args:
            manager: SessionControlManager instance
        """
        self.manager = manager

    def handle_intervention(self, context: InterventionContext) -> str:
        """Handle intervention without interactive prompt.

        Args:
            context: Intervention context

        Returns:
            Session ID
        """
        session_id = self.manager.request_intervention(context)
        return session_id

    async def auto_resume(self, session_id: str, mock_actions: Optional[list] = None) -> dict:
        """Automatically resume with optional mock actions.

        Args:
            session_id: Session ID
            mock_actions: Optional list of mock actions to record

        Returns:
            Final state
        """
        if mock_actions:
            for action in mock_actions:
                self.manager.record_human_action(action)
        
        return await self.manager.resume_automation(session_id)
