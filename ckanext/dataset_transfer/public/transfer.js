$(document).ready(function(){
    
    // let dest_url = $('#org_list_call').val();
    // let req = new XMLHttpRequest();
    // req.onreadystatechange = function() {
    //     if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
    //         $('#dataset_transfer_org_list').select2({data:res});                            
    //     }
    // }
    // req.open("GET", dest_url);


    $.ajax({
        url: $('#org_list_call').val(),
        cache:false,   
        // dataType: 'json',     
        type: "GET",
        success: function(result){                         
             $('#dataset_transfer_org_list').select2({
                 data:JSON.parse(result),
                width:'50%'
            }); 
        }
    });
    
    
    
    
    
   


});