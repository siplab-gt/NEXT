/*
  next-widget.js - A javascript library to download widgets from the next service.
*/

var next_widget = (function($){
    var _url = "localhost";
    var _args = null;
    var _callbacks = null;
    var _queryTime = 0;
    var _timeout = 120000;   // ms per request; 0 = browser default (no limit)
    // Callback contract (all extra arguments are optional, older pages ignore them):
    //   getQuery_success(data)
    //   processAnswer_success(data)
    //   widget_failure(jqXHR, textStatus, errorThrown, phase, data)
    //     phase is "getQuery" or "processAnswer"; textStatus is jQuery's
    //     ("timeout", "error", "abort", "parsererror") or "appfail" when the
    //     server answered 200 but with a FAIL meta / no widget.
    return {	

	setUrl : function(url) {      
	    _url = url;
	},
	setOptions : function(opts) {
	    if (opts && typeof opts.timeout === "number") { _timeout = opts.timeout; }
	},
	getQuery : function(div_id,args,callbacks){
	    $.ajax({
		url: _url+"/api/experiment/getQuery",
		type: "POST",
		contentType: "application/json",
		data: JSON.stringify(args),
		dataType: "json",
		timeout: _timeout
	    }).done( function(data,textStatus, jqXHR) {
		// A 200 can still be a failure: the app raised inside getQuery and the
		// API returned {"meta": {"status": "FAIL", ...}} with no widget html.
		if (!data || !data.html || !data.args || (data.meta && data.meta.status === "FAIL")) {
		    var msg = (data && data.meta && data.meta.message) ? data.meta.message : "no widget in response";
		    console.log("getQuery returned 200 without a widget", data);
		    callbacks.widget_failure(jqXHR, "appfail", msg, "getQuery", data);
		    return;
		}
		// Set the div to this html
		$('#'+div_id).html(data.html);
		_queryTime = new Date().getTime();
		// Build args dictionary for the processAnswer call
		_args = {};
		_args["exp_uid"] = args["exp_uid"];
		_args["args"] = {};
		console.log(data.args)
		console.log(data.args["query_uid"])
		
		_args["args"]["query_uid"] = data.args["query_uid"]; 
		
		// Set the callbacks
		_callbacks = callbacks;
		_callbacks.getQuery_success(data);

	    }).fail( function(jqXHR, textStatus, errorThrown){
		console.log("Failed to get widget data", jqXHR, textStatus, errorThrown);
		callbacks.widget_failure(jqXHR, textStatus, errorThrown, "getQuery");
	    });
	},	

	processAnswer: function(args, query_meta) {
	    if (_args === null || _callbacks === null) {
		console.log("processAnswer called before a query was served");
		return;
	    }
	    $.extend(_args["args"], args);
	    currTime = new Date().getTime();
	    _args["args"]["response_time"] = (currTime -  _queryTime)/1000.;
	    console.log(_args);
	    $.ajax({
		url: _url+"/api/experiment/processAnswer",
		type: "POST",
		contentType: "application/json",
		data: JSON.stringify(_args),
		timeout: _timeout
	    }).done( function(data, textStatus,XHR){
		_callbacks.processAnswer_success(data);
	    } ).fail(function(jqXHR, textStatus, errorThrown){
		console.log("Error in communicating with next_backend", jqXHR, textStatus, errorThrown);
		_callbacks.widget_failure(jqXHR, textStatus, errorThrown, "processAnswer");
	    });
	},
	
	shuffle: function(array) {
	    var currentIndex = array.length, temporaryValue, randomIndex ;
	    while (0 !== currentIndex) {
		randomIndex = Math.floor(Math.random() * currentIndex);
		currentIndex -= 1;
		temporaryValue = array[currentIndex];
		array[currentIndex] = array[randomIndex];
		array[randomIndex] = temporaryValue;
	    }
	    return array;
	},

	getQueryVars : function() {
	    var query = window.location.search.substring(1);
	    var vars = query.split('&');
	    var pair = {};
	    for (var i = 0; i < vars.length; i++) {
		key_val = vars[i].split('='); 
		pair[key_val[0]] = key_val[1];
	    }
	    return pair;
	},
	
	makeRandomString : function(length){
	    var text = "";
	    var possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
	    for( var i=0; i < length; i++ ){
		text += possible.charAt(Math.floor(Math.random() * possible.length));
	    }
	    return text;
	}
    };
})(jQuery);
