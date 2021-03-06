######
# Imports
######

import requests
from datetime import datetime, timezone
import pandas as pd
import re
from dotenv import dotenv_values

######
# Configuration
######

env_config = dotenv_values(".env")
api_key = env_config["CLOCKIFYAPI"]
sheet_id = env_config["SHEETID"]

headers = {'x-api-key': api_key}
sheet_base_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet="

r = requests.get('https://hubspot.clockify.me/api/v1/user', headers=headers)
context = r.json()
my_id = context["id"]
workspace = context["activeWorkspace"]

min_adjusted_meeting_length = 0.5 # fraction
max_meeting_start_delay = 0.33 # fraction

max_email_minutes = 15 # minutes
min_email_minutes = 5 # minutes
max_email_overlap = 3 # minutes, should be smaller than min_email_minutes

common_tags = {
    "meeting": "6172fd18d19f7568cf220734",
    "email": "6172fd18d19f7568cf2207ba",
    "investigate": "6172fd18d19f7568cf2207de",
    "post_call": "6172fd18d19f7568cf220758",
    "pre_call": "6172fd18d19f7568cf2207ef",
    "day_prep": "6172fd18d19f7568cf220817",
    "weekly_catchup": "6172fd1dd19f7568cf220c38",
    "lunch": "6172fd1ad19f7568cf2209cd"
}




######
# Utility functions
######

def isostr_to_ms(iso_str):
    if not iso_str:
        return int(datetime.now().timestamp() * 1000)
    else:
        assert iso_str[-1] == "Z"
        return int(1000 * datetime.fromisoformat(iso_str[:-1] + "+00:00").timestamp())

def get_intervals(minus_x_hours = 48):
    lower_bound = int((datetime.now().timestamp() - minus_x_hours * 60 * 60 ) * 1000)
    page_size = 0
    completed = False
    while page_size < 1000 and completed == False:
        page_size += 50
        intervals = []
        r = requests.get("https://hubspot.clockify.me/api/v1/workspaces/" + workspace + "/user/" + my_id + "/time-entries?page-size=" + str(page_size), headers=headers)
        my_time_entries = r.json()
        for time_entry in my_time_entries:
            assert time_entry["timeInterval"]["start"][-1] == "Z"
            time_start = isostr_to_ms(time_entry["timeInterval"]["start"])
            time_end = isostr_to_ms(time_entry["timeInterval"]["end"])
            if time_end > lower_bound:
                intervals.append([time_start, time_end])
            else:
                completed = True
                break
    return intervals

def tag_activity(activity):
    # TODO implement tag_activity based off a configuration file
    return common_tags["lunch"]

def map_domain(domain):
    try:
        row = customer_data.loc[domain]
        return row.project_id, row.tag_id, row.customer_alias
    except KeyError:
        print(domain + " not found in customer_data")
        return None, None, None

def map_domain_csv(domain_csv):
    domains = domain_csv.split(";")
    for domain in domains:
        project, tag, customer_alias = map_domain(domain)
        if project and tag:
            return project, tag, customer_alias
    return None, None, None

def sanitize(description):
    description = re.sub(r"[^a-zA-Z0-9]"," ",description)
    if description == "":
        return ""
    while "  " in description:
        description = description.replace("  "," ")
    if description[-1] == " ":
        description = description[:-1]
    return description.replace("  ", " ")

def log_activity(from_timestamp, to_timestamp, description, project_str, tag_list, billable):
    from_isoZ = datetime.fromtimestamp(from_timestamp/1000, timezone.utc).isoformat()[:-6]+'.000Z'
    to_isoZ = datetime.fromtimestamp(to_timestamp/1000, timezone.utc).isoformat()[:-6]+'.000Z'
    data = {
        "start": from_isoZ,
        "end": to_isoZ,
        "billable": billable,
        "projectId": project_str,
        "tagIds": tag_list,
        "description": description
    }
    r = requests.post("https://hubspot.clockify.me/api/v1/workspaces/" + workspace + "/time-entries", headers=headers, json = data)
    if r:
        print("ok")
        return True
    else:
        print("request failure")
        return False

def effective_meeting_times(from_timestamp, to_timestamp):
    skip = False
    original_length = to_timestamp - from_timestamp
    latest_start_date = from_timestamp + original_length * max_meeting_start_delay
    for interval in logged_intervals:
        if latest_start_date > interval[1] > from_timestamp:
            from_timestamp = interval[1]
    for interval in logged_intervals:
        if to_timestamp < interval[0] < to_timestamp:
            to_timestamp = interval[0]
    if (to_timestamp - from_timestamp) < original_length * min_adjusted_meeting_length:
        skip = True
    for interval in logged_intervals:
        if interval[0] < to_timestamp and interval[1] > from_timestamp:
            skip = True
    if skip:
        return None, None
    else:
        return from_timestamp, to_timestamp

def effective_email_times(send_timestamp):
    skip = False
    upper_bound = send_timestamp
    for interval in logged_intervals:
        if interval[1] > send_timestamp and interval[0] < upper_bound:
            upper_bound = interval[0]
    upper_bound = min(upper_bound, send_timestamp)
    for interval in logged_intervals:
        lower_bound = upper_bound - max_email_minutes * 1000 * 60
        if interval[0] < upper_bound and interval[1] > lower_bound:
            lower_bound = interval[1]
    if (upper_bound - lower_bound) * 1000 * 60 < min_email_minutes:
        skip = True
    if (send_timestamp - upper_bound) * 1000 * 60 > max_email_overlap:
        skip = True
    # this loop may be redundant, not sure
    for interval in logged_intervals:
        if interval[0] < upper_bound and interval[1] > lower_bound:
            skip = True
    if skip:
        return None, None
    else:
        return lower_bound, upper_bound


######
# Process Input Files
######

customer_domains = pd.read_csv("input_files/customer_domains.csv",
                               usecols=["domain", "customer_alias"],
                               dtype={"domain": "string", "customer_alias": "string"})

tag_alias = pd.read_csv("input_files/tag_alias.csv",
                        usecols=["tag_alias", "tag_id"],
                        dtype={"tag_alias": "string", "tag_id": "string"},
                        index_col = "tag_alias")

customer_project_tag = pd.read_csv("input_files/customer_project_tag.csv",
                                   usecols=["customer_alias", "hub_id", "tag_alias", "project_id"],
                                   dtype={"customer_alias": "string", "hub_id": "int64", "tag_alias": "string", "project_id": "string"},
                                   index_col = "customer_alias")

customer_data = pd.merge(customer_domains, customer_project_tag, on="customer_alias", how="left")
customer_data = pd.merge(customer_data, tag_alias, on="tag_alias", how="left").set_index("domain").drop(columns=["tag_alias"])

######
# data loading
######

meetings = pd.read_csv(sheet_base_url + "customer_meetings",
                       usecols=["start_timestamp", "end_timestamp", "event_summary", "recipient_domains"],
                       dtype={"start_timestamp": "int64", "end_timestamp": "int64"})
#print(meetings)
meetings["project"] = meetings.apply(lambda x: map_domain_csv(x["recipient_domains"])[0], axis=1)
meetings["tag"] = meetings.apply(lambda x: map_domain_csv(x["recipient_domains"])[1], axis=1)
meetings["customer_alias"] = meetings.apply(lambda x: map_domain_csv(x["recipient_domains"])[2], axis=1)
meetings["event_summary"] = meetings.apply(lambda x: sanitize(x["event_summary"]).lower().strip(), axis=1)
meetings = meetings[["start_timestamp", "end_timestamp", "event_summary","project", "tag", "customer_alias"]].sort_values(by=['start_timestamp'])


email_sent = pd.read_csv(sheet_base_url + "email_sent",
                         usecols=["send_timestamp", "subject", "recipient_domains"],
                         dtype={"send_timestamp": "int64"})
email_sent["project"] = email_sent.apply(lambda x: map_domain_csv(x["recipient_domains"])[0], axis=1)
email_sent["tag"] = email_sent.apply(lambda x: map_domain_csv(x["recipient_domains"])[1], axis=1)
email_sent["customer_alias"] = email_sent.apply(lambda x: map_domain_csv(x["recipient_domains"])[2], axis=1)
email_sent["subject"] = email_sent.apply(lambda x: sanitize(x["subject"]).lower().strip(), axis=1)
email_sent = email_sent[["send_timestamp", "subject", "project", "tag", "customer_alias"]].sort_values(by=['send_timestamp'])

logged_intervals = get_intervals(120)


######
# external interface
######

def tag_activities():
    # TODO tag existing activities based on input files (cf. update_input_files function)
    # TODO find a way to log internal meetings, too
    pass

def log_meetings(silent=False):
    # TODO in GAS, exclude meetings everybody but yourself have declined (optional?)
    for index, row in meetings[~meetings.project.isna()].iterrows():
        from_timestamp, to_timestamp = effective_meeting_times(row['start_timestamp'], row['end_timestamp'])
        if from_timestamp and to_timestamp and row['project'] and row['tag']:
            r = log_activity(from_timestamp, to_timestamp, "MEETING " + row['event_summary'], row['project'], [row['tag'], common_tags["meeting"]], True)
            if r:
                if not silent:
                    print("Logged meeting (" + str(round((to_timestamp - from_timestamp)/(1000 * 60)))+ "min) " + "\"" + row['event_summary'] + "\" to " + row['customer_alias'].upper() )
                logged_intervals.append([from_timestamp, to_timestamp])
                # TODO log adjacent pre_call and post_call activities
            else:
                print("FAILED to log meeting \"" + row['event_summary'] + "\" to " + row['customer_alias'].upper() )
        else:
            print("Cannot log meeting \"" + row['event_summary'] + "\" to " + row['customer_alias'].upper() + " (coincides with logged activity)")

def log_email(silent=False):
    for index, row in email_sent[~email_sent.project.isna()].iterrows():
        from_timestamp, to_timestamp = effective_email_times(row['send_timestamp'])
        if from_timestamp and to_timestamp and row['project'] and row['tag']:
            print("tried")
            r = log_activity(from_timestamp, to_timestamp, "EMAIL " + row['subject'], row['project'], [row['tag'], common_tags["email"]], True)
            if r:
                if not silent:
                    print("Logged email (" + str(round((to_timestamp - from_timestamp)/(1000 * 60)))+ "min) " + "\"" + row['subject'] + "\" to " + row['customer_alias'].upper() )
                logged_intervals.append([from_timestamp, to_timestamp])
            else:
                print("FAILED to log email \"" + row['subject'] + "\" to " + row['customer_alias'].upper() )
        else:
            print("Cannot log email \"" + row['subject'] + "\" to " + row['customer_alias'].upper() + " (coincides with logged activity)")

def fill_general_time(from_iso, until_iso, total_hours_max = 8):
    # TODO white noise function
    pass

######
# main
######

if __name__ == "__main__":
    # tag_activities()
    #log_meetings()
    #log_email()
    # fill_general_time (whatever params)
    customer_data.to_csv("combined_customer_data.csv")
    print("END")