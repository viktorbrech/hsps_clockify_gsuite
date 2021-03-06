/**
 * This is a Google Apps Script, to be deployed with a Google sheet container.
 * Two sheets should exist, "email_sent" and "customer_meetings".
 * Access to Calendar API needs to be added as a service.
 */

function onOpen() {
  var spreadsheet = SpreadsheetApp.getActive();
  var menuItems = [
    //{name: 'Validate content (placeholder)', functionName: 'validateSheet_'},
    {name: 'Refresh email and calendar data', functionName: 'refreshSheet_'}
  ];
  spreadsheet.addMenu('Clockifyiable_Activities', menuItems);
}

function refreshSheet_() {
  getRecentSentEmail();
  getRecentMeetings();
}


let config_map = {}

function getConfig() {
  let ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("config");
  // This represents ALL the data
  var range = sheet.getDataRange();
  var values = range.getValues();
  // This logs the spreadsheet in CSV format with a trailing comma
  for (var i = 0; i < values.length; i++) {
    config_map[values[i][0]] = values[i][1];
  }
}

// via https://www.weirdgeek.com/2019/10/regular-expression-in-google-apps-script/ and https://stackoverflow.com/questions/42407785/regex-extract-email-from-strings
// cf. https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/match
function getRecipientEmails(string) {
    var regExp = new RegExp("([a-zA-Z0-9+._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)","gi"); 
    var results = string.match(regExp);
    return results;
    }

// https://developers.google.com/apps-script/reference/gmail
function getRecentSentEmail() {
  getConfig();
  let ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("email_sent");
  sheet.clear();
  sheet.appendRow(["send_timestamp", "subject", "recipient_domains"]);
  let threads = GmailApp.search("in:sent", 0, 100);
  for (var i = 0; i < threads.length; i++) {
    let messages = threads[i].getMessages();
    for (var j = messages.length - 1; j >= 0 ; j--) {
      if (messages[j].getFrom().includes(config_map["sender_email"])) {
        let message_date = messages[j].getDate();
        if ((Date.now() - message_date)/(1000*60*60) < config_map["hours"]) {
          let message_subject = messages[j].getSubject()
          if (message_subject && !message_subject.includes("out of office") && !message_subject.includes("slow to respond")) {
            let message_recipients = messages[j].getTo();
            let message_cc = messages[j].getCc();
            if (message_cc.length > 0) {
              message_recipients = message_recipients + ", " + message_cc
            }
            let recipients = getRecipientEmails(message_recipients);
            let recipient_domains = []
            for (var k = 0; k < recipients.length; k++) {
              recipient_domain = recipients[k].split("@")[1];
              if (!recipient_domains.includes(recipient_domain) && recipient_domain != "hubspot.com" && recipient_domain != "gmail.com" && !recipient_domain.includes("google.com")) {
                recipient_domains.push(recipient_domain);
              }
            }
            if (recipient_domains.length > 0) {
              sheet.appendRow([message_date.getTime(), message_subject, recipient_domains.join(";")]);
            }
          }
        }
      }
    }
  }
}

// https://developers.google.com/apps-script/guides/services/advanced
// https://developers.google.com/calendar/api/v3/reference/events 
// unfortunately couldn't use https://developers.google.com/apps-script/reference/calendar/calendar-app since it doesn't return "decline" status for an event owner
function getRecentMeetings() {
  getConfig();
  let ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("customer_meetings");
  sheet.clear();
  sheet.appendRow(["start_timestamp", "end_timestamp", "event_summary", "recipient_domains"]);
  let calendarId = 'primary';
  let now = new Date();
  let now_minus_one_day = new Date(now.getTime() - (config_map["hours"] * 60 * 60 * 1000));
  let events = Calendar.Events.list(calendarId, {
    timeMin: now_minus_one_day.toISOString(),
    timeMax: now.toISOString(),
    singleEvents: true,
    orderBy: 'startTime',
    maxResults: 100
  });
  if (events.items && events.items.length > 0) {
    for (var i = 0; i < events.items.length; i++) {
      let event = events.items[i];
      if (!event.start.date) {
        log_event = true;
        let event_domains = []
        if (event.attendees && event.attendees.length > 0) {
          for (var k = 0; k < event.attendees.length; k++) {
            let attendee = event.attendees[k]
            //Logger.log(attendee.email);
            if (attendee.self) {
              if (attendee.responseStatus == "declined") {
                log_event = false;
              }
            } else {
              let attendee_domain = attendee.email.split("@")[1]
              if (!event_domains.includes(attendee_domain) && attendee_domain != "hubspot.com" && attendee_domain != "gmail.com" && !attendee_domain.includes("google.com")) {
                event_domains.push(attendee_domain);
              }
            }
          }
        }
        if (event_domains.length == 0) {
          log_event = false
        }
        if (log_event) {
          let event_start = Date.parse(event.start.dateTime);
          let event_end = Date.parse(event.end.dateTime);
          sheet.appendRow([event_start, event_end, event.summary, event_domains.join(";")]);
        }
      }
    }
  }
}