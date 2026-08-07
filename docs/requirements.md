# Requirements

## Project: PeriScribe

This is a tool for systematic gathering and symbolization of fire geography for fire behavior analysis.

Fire geography is pulled from configurable data sources at regular time intervals and symbolized in a way that indicates the growth of fires over time. Each fire has a point associated with it (e.g., with a flame icon as a symbol) and perimeter for each day that the fire is actively mapped. When there is more than one perimeter for a fire on a given day, the latest perimeter for that day is used. The perimeters are symbolized in a way that indicates the growth of fires from day to day.

## Notifications

When the output KML files are updated, a notification is sent to a configurable list of recipients. The notification includes a description of changes.

## Configuration

### Data Sources and Notification Recipients

There is a JSON file that contains a list of data sources. Each data source has properties indicating how to pull the data and when (time based? frequency based? triggered? multiple of these options?).

The same JSON file contains a list of notification recipients. Each recipient has properties indicating how to send the notification (email? text message? other?) and when (e.g., Any perimeter grew by a certain percentage or number of acres? Update to a fire that started in the last day and is over a certain number of acres?).

There will eventually be a simple web-based tool that provides a UI for creating / editing this JSON file.

### Symbolization

There is a template file in KML format. It contains a fictional point location and a set of fictional daily perimeters for a single fictional fire. The actual location of those geographic elements do not matter. The point is named "Fire-Point-Location". The perimeters are named "Day-Minus-0", "Day-Minus-1", "Day-Minus-2", "Day-Minus-3", etc. When symbolizing real fire data, the styles associated with the fictional fire are used. This allows Google Earth, or other KML tools, to be used as the UI for specifying symbolization.

### Cached Data Location

This might be an object store like Amazon S3, an SFTP server, or a local file system (use rclone to enable many different kinds of data stores without having to implement them?).

### KML Output Location

This might be an object store like Amazon S3, an SFTP server, or a local file system (use rclone to enable many different kinds of data stores without having to implement them?).
